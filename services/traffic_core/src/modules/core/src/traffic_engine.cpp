#include "core/traffic_engine.hpp"
#include "common/net/inproc_transport.hpp"
#include "data_provider/scenario_generator.hpp"

#include "core/telemetry_worker.hpp"
#include <atomic>
#include <chrono>
#include <cstdint>
#include <expected>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace traffic::core {

#if TRAFFIC_DISABLE_ROUTER_BPR
constexpr bool ROUTER_TRAFFIC_ENABLED = false;
#else
constexpr bool ROUTER_TRAFFIC_ENABLED = true;
#endif

#if TRAFFIC_ENABLE_ROUTER_PROFILE
constexpr bool ROUTER_PROFILE_ENABLED = true;
#else
constexpr bool ROUTER_PROFILE_ENABLED = false;
#endif

using traffic::common::net::RouteRequest;
using traffic::common::net::RouteResponse;

TrafficEngine::TrafficEngine()
    : is_initialized_(false), keep_running_(true), num_agents_(0),
      last_respawn_idx_(0), current_sim_time_(0.0f), last_mpr_tick_sim_sec_(0),
      routes_computed_(0), target_accel_(1000.0f),
      router_pool_(TRAFFIC_ROUTER_THREADS, true),
      kin_system_(agent_pool_, route_arena_) {
  mpr_requests_buffer_.reserve(4096);
  last_telemetry_time_ = std::chrono::steady_clock::now();
}

TrafficEngine::TrafficEngine(const std::vector<int> &router_cores)
    : is_initialized_(false), keep_running_(true), num_agents_(0),
      last_respawn_idx_(0), current_sim_time_(0.0f), last_mpr_tick_sim_sec_(0),
      routes_computed_(0), router_pool_(router_cores),
      kin_system_(agent_pool_, route_arena_) {
  mpr_requests_buffer_.reserve(4096);
}

TrafficEngine::~TrafficEngine() { Stop(); }

std::expected<void, std::string>
TrafficEngine::Init(const std::string &data_path) {
  auto graph_status = router_manager_.LoadGraphs(data_path);
  if (!graph_status) {
    return std::unexpected(graph_status.error());
  }

  auto mpr_transport = std::make_unique<common::net::InProcTransport>();
  auto router_transport = std::make_unique<common::net::InProcTransport>();

  // Link transports for zero-copy in-process communication
  mpr_transport->SetRemote(router_transport.get());
  router_transport->SetRemote(mpr_transport.get());

  mpr_ep_ =
      std::make_unique<common::net::TypedEndpoint<RouteRequest, RouteResponse>>(
          std::move(mpr_transport));
  router_ep_ =
      std::make_unique<common::net::TypedEndpoint<RouteResponse, RouteRequest>>(
          std::move(router_transport));

  mpr_engine_ = std::make_unique<decision_engine::MprEngine>();

  is_initialized_ = true;
  StartRouterWorker();

  // Pre-build per-edge occupancy and lengths for PhysicsContext (avoids
  // geometry_store lookup per tick)
  size_t n_edges = static_cast<size_t>(router_manager_.num_edges());
  live_edge_volumes_.assign(n_edges, 0);
  max_live_volumes_.assign(n_edges, 0);
  edge_lengths_cache_.resize(n_edges);
  queue_edge_volumes_ = std::make_unique<std::atomic<uint32_t>[]>(n_edges);
  for (size_t i = 0; i < n_edges; ++i) {
    edge_lengths_cache_[i] =
        router_manager_.get_edge_length(static_cast<traffic::EdgeID>(i));
    queue_edge_volumes_[i].store(0, std::memory_order_relaxed);
  }

  if (router_manager_.get_geometry_store()) {
    hub_scenario_mgr_.LoadConfig(
        data_path + "/../configs/simulation/scenario.yaml",
        router_manager_.get_geometry_store(),
        static_cast<uint32_t>(router_manager_.num_edges()));
  }

  return {};
}

void TrafficEngine::ResetState() {
  // Ensure the router worker is completely stopped before we start resetting
  // state to prevent any async queue insertions during clear.
  bool was_running = keep_running_.load();
  if (was_running) {
    keep_running_ = false;
    router_pool_.SetPaused(false); // wake up if paused
    router_pool_.ClearTasks();
    if (router_worker_.joinable()) {
      router_worker_.join();
    }
  }

  router_pool_.ClearTasks();
  router_ep_->Clear();
  mpr_ep_->Clear();

  route_arena_.agent_spans.clear();
  route_arena_.flat_edges.clear();
  route_arena_.flat_etas_sec.clear();

  if constexpr (ROUTER_TRAFFIC_ENABLED) {
    auto vol_mgr = router_manager_.get_volume_manager();
    if (vol_mgr) {
      vol_mgr->Clear();
    }
  }

  num_agents_ = 0;
  last_respawn_idx_ = 0;
  routes_computed_.store(0);
  total_visited_nodes_.store(0);
  total_route_cycles_.store(0);
  profiled_routes_count_.store(0);
  total_completed_routes_ = 0;
  total_successful_routes_ = 0;
  total_failed_routes_ = 0;
  total_discarded_routes_ = 0;
  total_stale_routes_ = 0;
  reroute_count_.store(0);
  total_spawns_.store(0);
  tti_count_.store(0);
  tti_sum_ = 0.0;
  current_sim_time_ = 0.0f;
  last_mpr_tick_sim_sec_ = 0;

  std::fill(live_edge_volumes_.begin(), live_edge_volumes_.end(), 0);
  std::fill(max_live_volumes_.begin(), max_live_volumes_.end(), 0);
  if (queue_edge_volumes_) {
    for (size_t i = 0; i < router_manager_.num_edges(); ++i) {
      queue_edge_volumes_[i].store(0, std::memory_order_relaxed);
    }
  }
  std::fill(agent_pool_.status.begin(), agent_pool_.status.end(), data_provider::AgentStatus::INACTIVE);
  std::fill(agent_pool_.in_queue.begin(), agent_pool_.in_queue.end(), 0);
  std::fill(trip_free_flow_sec_.begin(), trip_free_flow_sec_.end(), 0.0f);
  std::fill(trip_spawn_sim_time_.begin(), trip_spawn_sim_time_.end(), 0.0f);

  if (num_agents_ > 0) {
    route_arena_.flat_edges.reserve(static_cast<size_t>(num_agents_) * 600);
    route_arena_.flat_etas_sec.reserve(static_cast<size_t>(num_agents_) * 600);
  }

  // Restart router worker if it was running
  if (was_running) {
    keep_running_ = true;
    StartRouterWorker();
  }
}

void TrafficEngine::SpawnAgents(uint32_t num_agents, uint16_t asf,
                                const std::vector<double> &wp_probs) {
  if (!is_initialized_)
    return;

  ResetState();
  num_agents_ = num_agents;
  asf_ = asf;

  std::vector<RouteRequest> initial_requests;

  data_provider::ScenarioGenerator::SpawnRandomAgents(
      agent_pool_, num_agents,
      static_cast<uint32_t>(router_manager_.num_edges()), asf, initial_requests,
      &hub_scenario_mgr_, static_cast<uint32_t>(current_sim_time_), wp_probs);

  // RouteArena resizes automatically in UpdateRoute

  // Allocate per-agent trip tracking buffers
  trip_free_flow_sec_.assign(num_agents, 0.0f);
  trip_spawn_sim_time_.assign(num_agents, 0.0f);

  // Send initial paths computation
  mpr_ep_->Send(initial_requests);

  for (uint32_t i = 0; i < num_agents; ++i) {
    float length = router_manager_.get_edge_length(agent_pool_.current_edge[i]);
    agent_pool_.inv_edge_length_m[i] =
        (length > 0.001f) ? (1.0f / length) : 1.0f;
  }
}

void TrafficEngine::Warmup(const std::atomic<bool> *abort_flag) {
  if (!is_initialized_)
    return;

  while (GetWaitingSpawnAgents() > 0) {
    if (abort_flag && !abort_flag->load())
      break;

    HandleResponses();
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
}

void TrafficEngine::Warmup(uint32_t num_agents,
                           const std::atomic<bool> *abort_flag) {
  SpawnAgents(num_agents, 50);
  Warmup(abort_flag);
}

void TrafficEngine::Run() {
  keep_running_ = true;
  const float dt = 0.1f; // High-precision 100ms physics steps

  while (keep_running_) {
    auto tick_start = std::chrono::steady_clock::now();

    Step(dt);
    UpdateTelemetry();

    // Throttling Logic
    auto tick_end = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
        tick_end - tick_start);

    float accel = target_accel_.load();
    if (accel > 0.0f) {
      auto target_micros = static_cast<long long>((dt / accel) * 1000000.0f);
      if (elapsed.count() < target_micros) {
        std::this_thread::sleep_for(
            std::chrono::microseconds(target_micros - elapsed.count()));
      }
    } else {
      // Paused: idle wait
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
  }
}

void TrafficEngine::UpdateTelemetry() {
  if (!telemetry_worker_)
    return;

  auto now = std::chrono::steady_clock::now();
  auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      now - last_telemetry_time_);

  // Throttle telemetry collection based on telemetry_fps_
  float interval_ms = 1000.0f / std::max(1.0f, telemetry_fps_.load());
  if (elapsed.count() < interval_ms)
    return;

  auto &buffer = telemetry_worker_->GetInactiveBuffer();
  buffer.clear();

  // Copy only active agents (SoA to AoS conversion for network)
  for (uint32_t i = 0; i < num_agents_; ++i) {
    if (agent_pool_.IsDriving(i)) {
      common::net::AgentState state;
      state.agent_id = i;
      state.current_edge = agent_pool_.current_edge[i];
      state.pos_meters = agent_pool_.pos_meters[i];
      buffer.push_back(state);
    }
  }

  common::net::TelemetryHeader header;
  header.tick_id = static_cast<uint32_t>(current_sim_time_ * 10); // 0.1s ticks
  header.current_sim_time = current_sim_time_;
  header.num_agents = static_cast<uint32_t>(buffer.size());

  // TPS calculation
  header.current_tps = 1000.0f / elapsed.count();

  telemetry_worker_->Publish(header);
  last_telemetry_time_ = now;
}
void TrafficEngine::Step(float dt) {
  if (!is_initialized_)
    return;

  float old_sim_time = current_sim_time_;

  // Phase 1: Locomotion with Sub-Stepping (Quantum Teleportation Prevention)
  const float MAX_SAFE_DT = 1.0f;
  int sub_steps = std::max(1, static_cast<int>(std::ceil(dt / MAX_SAFE_DT)));
  float actual_dt = dt / static_cast<float>(sub_steps);

  std::vector<uint32_t> completed_agents_buf;

  for (int i = 0; i < sub_steps; ++i) {
    auto ctx = MakePhysicsContext(static_cast<uint32_t>(current_sim_time_));
    ctx.completed_agents_out = &completed_agents_buf;

    kin_system_.AdvanceKinematics(actual_dt, ctx);
    total_completed_routes_ += kin_system_.ProcessTransitions(ctx);
    current_sim_time_ += actual_dt;

    // Process completed agents for TTI calculation
    if (!completed_agents_buf.empty()) {
      double local_tti_sum = 0.0;
      uint32_t local_tti_count = 0;

      for (uint32_t agent_id : completed_agents_buf) {
        float free_flow = trip_free_flow_sec_[agent_id];
        float real_time = current_sim_time_ - trip_spawn_sim_time_[agent_id];

        if (free_flow > 1.0f && real_time > 1.0f) {
          local_tti_sum += static_cast<double>(real_time / free_flow);
          local_tti_count++;
        }
      }

      if (local_tti_count > 0) {
        tti_count_.fetch_add(local_tti_count, std::memory_order_relaxed);
        // Simple non-atomic sum since this is the only writer thread (engine
        // step)
        tti_sum_ += local_tti_sum;
      }
      completed_agents_buf.clear();
    }
  }

  // Watchdog: Clean up any phantom agents stuck in limbo (IsDriving with empty route and not waiting for route)
  uint32_t total_pool = static_cast<uint32_t>(agent_pool_.status.size());
  for (uint32_t i = 0; i < total_pool; ++i) {
    if (agent_pool_.IsDriving(i) && agent_pool_.is_waiting_route[i] == 0) {
      if (route_arena_.GetRoute(i).empty()) {
        agent_pool_.status[i] = data_provider::AgentStatus::INACTIVE;
      }
    }
  }

  // Phase 2: Decision Making (MPR - Mesoscopic Path Rerouting)
  uint32_t sim_sec = static_cast<uint32_t>(current_sim_time_);
  while (sim_sec > last_mpr_tick_sim_sec_) {
    last_mpr_tick_sim_sec_++;
    // Допустим, роутер держит 4000 QPS.
    // ticks_per_real_sec = 25.0f * (accel / 10.0f);
    // tokens_this_tick = 4000 / ticks_per_real_sec;
    float accel = target_accel_.load();
    int reroute_tokens =
        std::max(1, static_cast<int>(4000.0f / (25.0f * (accel / 10.0f))));

    mpr_requests_buffer_.clear();
    mpr_engine_->Tick(last_mpr_tick_sim_sec_, agent_pool_, route_arena_,
                      mpr_requests_buffer_, reroute_tokens);

    if (!mpr_requests_buffer_.empty()) {
      if constexpr (ROUTER_TRAFFIC_ENABLED) {
        auto vol_mgr = router_manager_.get_volume_manager();
        if (vol_mgr) {
          for (const auto &req : mpr_requests_buffer_) {
            auto path = route_arena_.GetRoute(req.agent_id);
            auto etas = route_arena_.GetEtas(req.agent_id);
            if (!path.empty())
              vol_mgr->unbook_route(path, etas, asf_);
          }
        }
      }
      mpr_ep_->Send(mpr_requests_buffer_);
    }
  }

  // Сдвигаем окно времени в корзинках, чтобы зачистить прошедший трафик
  if constexpr (ROUTER_TRAFFIC_ENABLED) {
    auto vol_mgr = router_manager_.get_volume_manager();
    if (vol_mgr) {
      vol_mgr->advance_time(static_cast<uint32_t>(old_sim_time),
                            static_cast<uint32_t>(current_sim_time_));
    }
  }

  // Phase 2.5: Agent Recirculation (Diurnal Active Volume Control & Zero-Teleportation Trip Chaining)
  if (respawn_enabled_.load()) {
    static std::mt19937 rec_gen{std::random_device{}()};

    uint32_t current_active = GetDrivingAgents() + GetReroutingAgents() + GetWaitingSpawnAgents() + GetVirtualBufferAgents();
    float target_ratio = hub_scenario_mgr_.GetTargetActiveRatio(static_cast<uint32_t>(current_sim_time_));
    uint32_t target_active = static_cast<uint32_t>(std::round(num_agents_ * target_ratio));

    if (current_active < target_active) {
      uint32_t needed = target_active - current_active;
      uint32_t respawn_quota = std::min(needed, 1000u);
      mpr_requests_buffer_.clear();

      uint32_t i = last_respawn_idx_;
      for (uint32_t count = 0; count < num_agents_ && respawn_quota > 0;
           ++count) {
        if (agent_pool_.status[i] == data_provider::AgentStatus::INACTIVE &&
            agent_pool_.is_waiting_route[i] == 0 &&
            hub_scenario_mgr_.ShouldWakeupAgent(i, agent_pool_, static_cast<uint32_t>(current_sim_time_), target_ratio, rec_gen)) {
          respawn_quota--;
          auto [start_edge, target_edge] = hub_scenario_mgr_.GeneratePairForAgent(
              i, agent_pool_, static_cast<uint32_t>(current_sim_time_),
              static_cast<uint32_t>(router_manager_.num_edges()), rec_gen);

          if (start_edge == 0) start_edge = (agent_pool_.home_edge[i] != 0) ? agent_pool_.home_edge[i] : 1;
          if (target_edge == 0) target_edge = (agent_pool_.work_edge[i] != 0) ? agent_pool_.work_edge[i] : 2;

          agent_pool_.current_edge[i] = start_edge;
          agent_pool_.pos_meters[i] = 0.0f;
          agent_pool_.velocity_mps[i] = 0.0f;
          // Сброс прогресса маршрута предыдущей поездки.
          // Без этого GetWaitingSpawnAgents() не учитывает агента (route_progress_idx > 0).
          agent_pool_.route_progress_idx[i] = 0;
          // Сброс эталонного времени свободного потока.
          // Без этого is_initial_spawn=false и HandleResponses выбросит маршрут как несоответствующий reroute.
          trip_free_flow_sec_[i] = 0.0f;
          trip_spawn_sim_time_[i] = current_sim_time_;

          float length = edge_lengths_cache_.empty()
                             ? router_manager_.get_edge_length(start_edge)
                             : edge_lengths_cache_[start_edge];
          agent_pool_.inv_edge_length_m[i] =
              (length > 0.001f) ? (1.0f / length) : 1.0f;

          // Статус остаётся INACTIVE до получения маршрута — кинематика не двигает машину до спавна.
          agent_pool_.status[i] = data_provider::AgentStatus::INACTIVE;
          agent_pool_.is_waiting_route[i] = 1;
          agent_pool_.route_epoch[i]++;

          agent_pool_.total_waypoints[i] = 2;
          agent_pool_.next_waypoint_idx[i] = 1;
          agent_pool_.waypoints[i][0] = start_edge;
          agent_pool_.waypoints[i][1] = target_edge;

          traffic::common::net::RouteRequest req;
          req.agent_id = i;
          req.epoch = agent_pool_.route_epoch[i];
          req.asf = asf_;
          req.current_time_sec = static_cast<uint32_t>(current_sim_time_);
          req.num_waypoints = 2;
          req.waypoints[0] = start_edge;
          req.waypoints[1] = target_edge;

          mpr_requests_buffer_.push_back(std::move(req));
        }
        i = (i + 1) % num_agents_;
      }
      last_respawn_idx_ = i;
    }
  }
  if (!mpr_requests_buffer_.empty()) {
    if constexpr (ROUTER_TRAFFIC_ENABLED) {
      auto vol_mgr = router_manager_.get_volume_manager();
      if (vol_mgr) {
        for (const auto &req : mpr_requests_buffer_) {
          auto path = route_arena_.GetRoute(req.agent_id);
          auto etas = route_arena_.GetEtas(req.agent_id);
          if (!path.empty())
            vol_mgr->unbook_route(path, etas, asf_);
        }
      }
    }
    mpr_ep_->Send(mpr_requests_buffer_);
  }

  // Phase 3: Route Integration (Apply responses to Route Arena)
  HandleResponses();
}

void TrafficEngine::ForceReroute(const std::vector<RouteRequest> &requests) {
  if (!is_initialized_ || requests.empty())
    return;
  mpr_ep_->Send(requests);
}

void TrafficEngine::Stop() {
  keep_running_ = false;
  router_pool_.Stop();
  if (router_worker_.joinable()) {
    router_worker_.join();
  }
}

void TrafficEngine::StartRouterWorker() {
  router_worker_ = std::thread([this]() {
    router_start_time_ = std::chrono::steady_clock::now();
    router_busy_time_us_ = 0;
#ifdef __linux__
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(TRAFFIC_DISPATCH_AFFINITY, &cpuset);
    pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset);
#endif
    std::vector<RouteRequest> req_batch;
    std::vector<RouteResponse> res_batch;
    uint32_t empty_polls = 0;

    while (keep_running_) {
      if (router_ep_->Receive(req_batch)) {
        auto start_time = std::chrono::steady_clock::now();

        // Preserve the earliest queue position but update the actual start
        // position for duplicates
        std::vector<RouteRequest> deduped_batch;
        deduped_batch.reserve(req_batch.size());
        std::unordered_map<uint32_t, size_t> agent_to_index;

        for (const auto &req : req_batch) {
          auto it = agent_to_index.find(req.agent_id);
          if (it != agent_to_index.end()) {
            deduped_batch[it->second] = req;
          } else {
            agent_to_index[req.agent_id] = deduped_batch.size();
            deduped_batch.push_back(req);
          }
        }
        req_batch = std::move(deduped_batch);

        res_batch.resize(req_batch.size());
        for (size_t i = 0; i < req_batch.size(); ++i) {
          router_pool_.Enqueue([this, &req = req_batch[i],
                                &res = res_batch[i]]() {
            // Fast lock-free pre-calculation check: abort if the request is
            // already outdated or superseded
            if (req.epoch != agent_pool_.route_epoch[req.agent_id] ||
                agent_pool_.is_waiting_route[req.agent_id] == 0) {
              res.agent_id = req.agent_id;
              res.epoch = req.epoch;
              res.success = false;
              return;
            }

            // Convert POD array to vector for the Router interface
            std::vector<traffic::NodeID> wp_vec;
            wp_vec.reserve(req.num_waypoints);
            for (uint8_t w = 0; w < req.num_waypoints; ++w) {
              wp_vec.push_back(req.waypoints[w]);
            }

            auto result = [&]() {
              if constexpr (ROUTER_PROFILE_ENABLED) {
                auto r_start = std::chrono::steady_clock::now();
                auto res =
                    router_manager_
                        .Route<ROUTER_TRAFFIC_ENABLED, ROUTER_PROFILE_ENABLED>(
                            wp_vec, req.current_time_sec);
                auto r_end = std::chrono::steady_clock::now();
                uint32_t r_us =
                    std::chrono::duration_cast<std::chrono::microseconds>(
                        r_end - r_start)
                        .count();

                route_time_sum_us_.fetch_add(r_us, std::memory_order_relaxed);
                route_time_count_.fetch_add(1, std::memory_order_relaxed);
                uint32_t current_max =
                    route_time_max_us_.load(std::memory_order_relaxed);
                while (r_us > current_max &&
                       !route_time_max_us_.compare_exchange_weak(
                           current_max, r_us, std::memory_order_relaxed))
                  ;
                return res;
              } else {
                return router_manager_
                    .Route<ROUTER_TRAFFIC_ENABLED, ROUTER_PROFILE_ENABLED>(
                        wp_vec, req.current_time_sec);
              }
            }();

            res.agent_id = req.agent_id;
            res.epoch = req.epoch;
            if (result) {
              res.success = true;
              res.path_len = static_cast<uint16_t>(std::min<size_t>(
                  result->path.size(), traffic::common::net::MAX_ROUTE_PATH));
              for (size_t j = 0; j < res.path_len; ++j) {
                res.path[j] = result->path[j];
                res.edge_etas_sec[j] = result->etas[j];
              }
              if constexpr (ROUTER_PROFILE_ENABLED) {
                res.visited_nodes_count = result->visited_nodes_count;
                res.route_cycles = result->route_cycles;
              } else {
                res.visited_nodes_count = 0;
                res.route_cycles = 0;
              }
            } else {
              res.success = false;
              res.visited_nodes_count = 0;
              res.route_cycles = 0;
            }
          });
        }

        std::chrono::steady_clock::time_point w_start;
        if constexpr (ROUTER_PROFILE_ENABLED) {
          w_start = std::chrono::steady_clock::now();
        }

        router_pool_.WaitForAll();

        if constexpr (ROUTER_PROFILE_ENABLED) {
          auto w_end = std::chrono::steady_clock::now();
          uint64_t w_us = std::chrono::duration_cast<std::chrono::microseconds>(
                              w_end - w_start)
                              .count();
          router_wait_time_us_.fetch_add(w_us, std::memory_order_relaxed);
        }

        size_t added = req_batch.size();
        routes_computed_.fetch_add(static_cast<uint32_t>(added),
                                   std::memory_order_relaxed);

        router_ep_->Send(res_batch);

        auto end_time = std::chrono::steady_clock::now();
        uint64_t elapsed_us =
            std::chrono::duration_cast<std::chrono::microseconds>(end_time -
                                                                  start_time)
                .count();
        router_busy_time_us_.fetch_add(elapsed_us, std::memory_order_relaxed);

        empty_polls = 0;
      } else {
        // Не жжем ядро, если запросов нет (Task: Optimization)
        if (empty_polls < 4000) {
          _mm_pause();
          empty_polls++;
        } else {
          std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
      }
    }
  });
}

void TrafficEngine::HandleResponses() {
  std::vector<RouteResponse> incoming_resps;
  while (mpr_ep_->Receive(incoming_resps)) {
    for (const auto &r : incoming_resps) {
      // Проверка актуальности запроса (route_epoch и дубликатов)
      if (r.epoch != agent_pool_.route_epoch[r.agent_id] ||
          agent_pool_.is_waiting_route[r.agent_id] == 0) {
        total_stale_routes_++;
        continue;
      }

      if (r.success) {
        const bool is_initial_spawn = (trip_free_flow_sec_[r.agent_id] == 0.0f);
        const bool was_reroute = !is_initial_spawn;

        // Verify that the agent is still on a valid segment of the calculated
        // path. If it has moved, but is still on one of the edges in the new
        // path, we align its progress index. Otherwise, if its current edge is
        // not found in the path, we discard it.
        int found_idx = -1;
        if (was_reroute && r.path_len > 0) {
          traffic::EdgeID curr_edge = agent_pool_.current_edge[r.agent_id];
          for (size_t k = 0; k < r.path_len; ++k) {
            if (r.path[k] == curr_edge) {
              found_idx = static_cast<int>(k);
              break;
            }
          }
          if (found_idx == -1) {
            // Current edge is not part of the calculated path. Discard it.
            total_discarded_routes_++;
            // Снимаем флаг ожидания, но если маршрут пустой — возобновим запрос
            agent_pool_.is_waiting_route[r.agent_id] = 0;
            if (route_arena_.GetRoute(r.agent_id).empty()) {
              agent_pool_.status[r.agent_id] = data_provider::AgentStatus::INACTIVE;
            }
            continue;
          }
        }

        // Успешный проверенный путь — снимаем флаг ожидания
        agent_pool_.is_waiting_route[r.agent_id] = 0;

        if constexpr (ROUTER_TRAFFIC_ENABLED) {
          auto vol_mgr = router_manager_.get_volume_manager();
          if (vol_mgr) {
            // Unbook old route first
            auto old_path = route_arena_.GetRoute(r.agent_id);
            auto old_etas = route_arena_.GetEtas(r.agent_id);
            if (!old_path.empty()) {
              vol_mgr->unbook_route(old_path, old_etas, asf_);
            }
          }
        }

        // Reroute counter vs Spawn counter
        if (was_reroute) {
          reroute_count_.fetch_add(1, std::memory_order_relaxed);
          if (found_idx >= 0) {
            agent_pool_.route_progress_idx[r.agent_id] = static_cast<uint16_t>(found_idx);
          }
        } else {
          total_spawns_.fetch_add(1, std::memory_order_relaxed);
          agent_pool_.route_progress_idx[r.agent_id] = 0;
          if (r.path_len > 0) {
            agent_pool_.current_edge[r.agent_id] = r.path[0];
          }
        }

        total_successful_routes_++;
        if constexpr (ROUTER_PROFILE_ENABLED) {
          total_visited_nodes_.fetch_add(r.visited_nodes_count,
                                         std::memory_order_relaxed);
          total_route_cycles_.fetch_add(r.route_cycles,
                                        std::memory_order_relaxed);
          profiled_routes_count_.fetch_add(1, std::memory_order_relaxed);
        }
        route_arena_.UpdateRoute(r.agent_id, {r.path.data(), r.path_len},
                                 {r.edge_etas_sec.data(), r.path_len});

        // TTI: record TRUE free-flow trip cost only at initial spawn
        if (!was_reroute && r.path_len > 0) {
          const auto *edge_attrs = router_manager_.get_edge_attributes_ptr();
          float free_flow_sec = 0.0f;
          for (size_t k = 0; k < r.path_len; ++k) {
            traffic::EdgeID segment = r.path[k];
            if (edge_attrs) {
              free_flow_sec += edge_attrs[segment].t_free_base;
            } else {
              float len = router_manager_.get_edge_length(segment);
              if (len < 0.1f)
                len = 0.1f;
              free_flow_sec += len / 15.0f;
            }
          }
          if (free_flow_sec < 0.1f)
            free_flow_sec = 0.1f;
          trip_free_flow_sec_[r.agent_id] = free_flow_sec;
          trip_spawn_sim_time_[r.agent_id] = current_sim_time_;
        }

        if constexpr (ROUTER_TRAFFIC_ENABLED) {
          auto vol_mgr = router_manager_.get_volume_manager();
          if (vol_mgr) {
            vol_mgr->book_route(route_arena_.GetRoute(r.agent_id),
                                route_arena_.GetEtas(r.agent_id),
                                asf_ /* weight */);
          }
        }

        if (!was_reroute) {
          agent_pool_.route_progress_idx[r.agent_id] = 0;
          agent_pool_.edge_enter_time_sec[r.agent_id] =
              static_cast<uint32_t>(current_sim_time_);

          traffic::EdgeID first_edge = route_arena_.GetRoute(r.agent_id)[0];
          float first_len = edge_lengths_cache_.empty()
                                ? router_manager_.get_edge_length(first_edge)
                                : edge_lengths_cache_[first_edge];
          if (first_len < 0.1f)
            first_len = 0.1f;
          agent_pool_.inv_edge_length_m[r.agent_id] = 1.0f / first_len;

          live_edge_volumes_[first_edge]++;
          if (live_edge_volumes_[first_edge] > max_live_volumes_[first_edge])
            max_live_volumes_[first_edge] = live_edge_volumes_[first_edge];

          agent_pool_.status[r.agent_id] = data_provider::AgentStatus::ACTIVE_FREE_FLOW;

          float w = (first_len / 15.0f);
          const auto *edge_attrs = router_manager_.get_edge_attributes_ptr();
          if (edge_attrs) {
            w = edge_attrs[first_edge].t_free_base;
          } else {
            const auto &view = router_manager_.get_view();
            if (view.static_weights) {
              w = static_cast<float>(view.static_weights[first_edge]);
            }
          }
          if (w < 0.001f)
            w = 0.001f;
          agent_pool_.velocity_mps[r.agent_id] = first_len / w;
        } else {
          agent_pool_.route_progress_idx[r.agent_id] = found_idx;
        }

        if (telemetry_worker_) {
          telemetry_worker_->SendEvent(common::net::EventType::SPAWN,
                                       r.agent_id,
                                       route_arena_.GetRoute(r.agent_id));
        }
      } else {
        total_failed_routes_++;
        // Маршрут не найден. Агент остается мертвым (или становится им) и ждет
        // квоту на респавн
        agent_pool_.status[r.agent_id] = data_provider::AgentStatus::INACTIVE;
      }
    }
  }
}

uint32_t TrafficEngine::GetActiveAgents() const {
  uint32_t active = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    if (agent_pool_.IsActive(i))
      active++;
  }
  return active;
}

TrafficEngine::AgentCounts TrafficEngine::GetAgentCounts() const {
  AgentCounts c;
  c.waiting_in_queue = static_cast<uint32_t>(agent_pool_.spillback_wait_queue.size());

  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    auto st = agent_pool_.status[i];
    bool waiting_route = (agent_pool_.is_waiting_route[i] == 1);

    if (st == data_provider::AgentStatus::VIRTUAL_BUFFER) {
      // Виртуальный буфер — всегда отдельная категория, независимо от is_waiting_route.
      c.virtual_buffer++;
    } else if (waiting_route) {
      if (agent_pool_.route_progress_idx[i] == 0) {
        c.waiting_spawn++;
      } else {
        c.rerouting++;
      }
    } else {
      if (st == data_provider::AgentStatus::ACTIVE_FREE_FLOW ||
          st == data_provider::AgentStatus::ACTIVE_QUEUE) {
        c.driving++;
      } else {
        c.idle++;
      }
    }
  }
  return c;
}

std::string TrafficEngine::GetAgentDebugSample(uint32_t requested_count) const {
  std::ostringstream json;
  json << "{\"sim_time\":" << current_sim_time_ << ",\"agents\":[";

  uint32_t total = static_cast<uint32_t>(agent_pool_.status.size());
  if (total == 0) {
    json << "]}";
    return json.str();
  }

  // 1. Фильтруем строго по АКТИВНЫМ агентам, находящимся физически на дорогах или в буфере
  std::vector<uint32_t> active_indices;
  active_indices.reserve(total);
  for (uint32_t i = 0; i < total; ++i) {
    if (agent_pool_.IsDriving(i)) {
      active_indices.push_back(i);
    }
  }

  uint32_t n_active = static_cast<uint32_t>(active_indices.size());
  uint32_t target_count = std::min(requested_count, n_active > 0 ? n_active : total);
  if (target_count == 0) target_count = 200;

  std::vector<uint32_t> sampled_indices;
  sampled_indices.reserve(target_count);

  if (n_active > 0) {
    // Равномерный шаг строго по АКТИВНЫМ агентам на дорогах
    uint32_t step = std::max(1u, n_active / target_count);
    for (uint32_t i = 0; i < n_active && sampled_indices.size() < target_count; i += step) {
      sampled_indices.push_back(active_indices[i]);
    }
    for (uint32_t i = 0; i < n_active && sampled_indices.size() < target_count; ++i) {
      if (i % step != 0) {
        sampled_indices.push_back(active_indices[i]);
      }
    }
  } else {
    uint32_t step = std::max(1u, total / target_count);
    for (uint32_t i = 0; i < total && sampled_indices.size() < target_count; i += step) {
      sampled_indices.push_back(i);
    }
  }

  bool first = true;
  uint32_t curr_sim_sec = static_cast<uint32_t>(current_sim_time_);

  for (uint32_t idx : sampled_indices) {
    if (!first) json << ",";
    first = false;

    const char* status_str = "INACTIVE";
    switch (agent_pool_.status[idx]) {
      case data_provider::AgentStatus::ACTIVE_FREE_FLOW: status_str = "ACTIVE_FREE_FLOW"; break;
      case data_provider::AgentStatus::ACTIVE_QUEUE: status_str = "ACTIVE_QUEUE"; break;
      case data_provider::AgentStatus::VIRTUAL_BUFFER: status_str = "VIRTUAL_BUFFER"; break;
      default: status_str = "INACTIVE"; break;
    }

    uint32_t wait_time = 0;
    if (agent_pool_.status[idx] == data_provider::AgentStatus::ACTIVE_QUEUE &&
        curr_sim_sec >= agent_pool_.spillback_start_time_sec[idx]) {
      wait_time = curr_sim_sec - agent_pool_.spillback_start_time_sec[idx];
    }

    float trip_duration = (agent_pool_.IsDriving(idx) && trip_spawn_sim_time_[idx] > 0.0f)
                              ? (current_sim_time_ - trip_spawn_sim_time_[idx])
                              : 0.0f;
    if (trip_duration < 0.0f) trip_duration = 0.0f;

    auto route = route_arena_.GetRoute(idx);
    uint32_t route_total_edges = static_cast<uint32_t>(route.size());

    json << "{"
         << "\"id\":" << idx << ","
         << "\"status\":\"" << status_str << "\","
         << "\"edge\":" << agent_pool_.current_edge[idx] << ","
         << "\"pos\":" << agent_pool_.pos_meters[idx] << ","
         << "\"v\":" << agent_pool_.velocity_mps[idx] << ","
         << "\"route_idx\":" << agent_pool_.route_progress_idx[idx] << ","
         << "\"route_total\":" << route_total_edges << ","
         << "\"trip_sec\":" << static_cast<uint32_t>(trip_duration) << ","
         << "\"in_queue\":" << static_cast<uint32_t>(agent_pool_.in_queue[idx]) << ","
         << "\"waiting_route\":" << static_cast<uint32_t>(agent_pool_.is_waiting_route[idx]) << ","
         << "\"spillback_wait_sec\":" << wait_time << ","
         << "\"pop_type\":" << static_cast<uint32_t>(agent_pool_.population_type[idx])
         << "}";
  }

  json << "]}";
  return json.str();
}

uint32_t TrafficEngine::GetDrivingAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    if (agent_pool_.IsDriving(i) && agent_pool_.is_waiting_route[i] == 0) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetReroutingAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    // Считаем перемаршрутизацию только для физически едущих агентов (не в виртуальном буфере).
    if (agent_pool_.status[i] != data_provider::AgentStatus::VIRTUAL_BUFFER &&
        agent_pool_.IsDriving(i) &&
        agent_pool_.is_waiting_route[i] == 1 &&
        agent_pool_.route_progress_idx[i] > 0) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetWaitingSpawnAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    if (agent_pool_.is_waiting_route[i] == 1 && agent_pool_.route_progress_idx[i] == 0) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetIdleAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    if (agent_pool_.status[i] == data_provider::AgentStatus::INACTIVE && agent_pool_.is_waiting_route[i] == 0) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetWaitingInQueueAgents() const {
  return static_cast<uint32_t>(agent_pool_.spillback_wait_queue.size());
}

uint32_t TrafficEngine::GetVirtualBufferAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.status.size(); ++i) {
    // Считаем ВСЕХ агентов в виртуальном буфере — в том числе тех, кто ждёт MPR ответа.
    if (agent_pool_.status[i] == data_provider::AgentStatus::VIRTUAL_BUFFER) {
      cnt++;
    }
  }
  return cnt;
}

float TrafficEngine::GetTrafficFlowPercent() const {
  const size_t agent_count = agent_pool_.Size();
  if (agent_count == 0) return 100.0f;

  double total_v_ratio = 0.0;
  uint32_t active_count = 0;

  for (size_t i = 0; i < agent_count; ++i) {
    if (agent_pool_.IsDriving(i)) {
      active_count++;
      float v_curr = agent_pool_.velocity_mps[i];
      float inv_len = agent_pool_.inv_edge_length_m[i];
      float edge_len = (inv_len > 0.0001f) ? (1.0f / inv_len) : 15.0f;
      float v_free = edge_len / 1.0f;
      if (v_free < 1.0f) v_free = 1.0f;
      float ratio = (v_curr / v_free);
      if (ratio > 1.0f) ratio = 1.0f;
      total_v_ratio += ratio;
    }
  }

  if (active_count == 0) return 100.0f;
  return static_cast<float>((total_v_ratio / active_count) * 100.0);
}

data_provider::PhysicsContext
TrafficEngine::MakePhysicsContext(uint32_t time_sec) const noexcept {
  data_provider::PhysicsContext ctx;
  ctx.current_time_sec = time_sec;
  ctx.asf = asf_;
  ctx.edge_lengths_m =
      edge_lengths_cache_.empty() ? nullptr : edge_lengths_cache_.data();
  ctx.live_volumes = const_cast<uint32_t *>(live_edge_volumes_.data());
  ctx.max_volumes = const_cast<uint32_t *>(max_live_volumes_.data());
  ctx.queue_volumes = queue_edge_volumes_.get();
  ctx.k_magic = router_manager_.get_kmagic_ptr();
  ctx.edge_attributes = router_manager_.get_edge_attributes_ptr();

  // Expose the static CSR weights (free-flow travel time per edge in seconds)
  const auto &view = router_manager_.get_view();
  ctx.static_weights = view.static_weights;

  // Подсистема противодействия заторам и дедлокам
  ctx.deadlock_mitigation_enabled = true;
  ctx.deadlock_mitigation_mode = 0; // 0: sumo_virtual_buffer, 1: cs_despawn_target
  ctx.time_to_teleport_sec = 300.0f;
  ctx.min_virtual_speed_mps = 1.3f;
  ctx.teleported_jam_count_out = const_cast<uint64_t *>(&teleported_jam_count_);

  return ctx;
}

void TrafficEngine::ApplySettings(float accel, float fps, float chaos) {
  target_accel_.store(accel);
  telemetry_fps_.store(fps);
  chaos_factor_.store(chaos);

  // Signal the Run() loop to reset its timing markers
  settings_changed_ = true;
}

bool TrafficEngine::IsBPREnabled() const noexcept {
  return ROUTER_TRAFFIC_ENABLED;
}

bool TrafficEngine::IsProfilingEnabled() const noexcept {
  return ROUTER_PROFILE_ENABLED;
}

} // namespace traffic::core
