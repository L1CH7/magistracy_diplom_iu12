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
  std::fill(agent_pool_.is_active.begin(), agent_pool_.is_active.end(), 0);
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
      wp_probs);

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

  size_t last_log = 0;
  while (routes_computed_.load() < num_agents_) {
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
    if (agent_pool_.is_active[i] == 1) {
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
    total_completed_routes_ += kin_system_.ProcessTransitions(ctx, dt);
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
        tti_sum_.fetch_add(local_tti_sum, std::memory_order_relaxed);
      }
      completed_agents_buf.clear();
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
    int reroute_tokens = std::max(
        1, static_cast<int>(
               static_cast<float>(TRAFFIC_ROUTER_MAX_QPS) /
               (static_cast<float>(TRAFFIC_BASE_FPS) * (accel / 10.0f))));

    mpr_requests_buffer_.clear();
    mpr_engine_->Tick(last_mpr_tick_sim_sec_, agent_pool_, route_arena_,
                      mpr_requests_buffer_, reroute_tokens);

    if (!mpr_requests_buffer_.empty()) {
      // Разбронирование старых маршрутов — только в HandleResponses,
      // чтобы избежать double-unbook и underflow uint16_t.
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

  // Phase 2.5: Agent Recirculation (Task 2 & 3: Rate Limiter)
  if (respawn_enabled_.load()) {
    static std::mt19937 rec_gen{std::random_device{}()};
    std::uniform_int_distribution<uint32_t> edge_dist(
        0, static_cast<uint32_t>(router_manager_.num_edges()) - 1);

    // Квота синхронизирована с пропускной способностью роутера (~4000 QPS).
    // Формула зеркальна reroute_tokens: не превышаем целевой RPS за тик,
    // чтобы не затапливать очередь в 357x быстрее ответов (было 1000/тик =
    // 100k/сек).
    float accel_for_quota = target_accel_.load();
    if (accel_for_quota < 0.01f)
      accel_for_quota = 0.01f;
    uint32_t respawn_quota = static_cast<uint32_t>(std::max(
        1, static_cast<int>(static_cast<float>(TRAFFIC_ROUTER_MAX_QPS) /
                            (static_cast<float>(TRAFFIC_BASE_FPS) *
                             (accel_for_quota / 10.0f)))));
    mpr_requests_buffer_.clear(); // Reuse buffer for respawn requests

    uint32_t i = last_respawn_idx_;
    for (uint32_t count = 0; count < num_agents_ && respawn_quota > 0;
         ++count) {
      if (agent_pool_.is_active[i] == 0 &&
          agent_pool_.is_waiting_route[i] == 0) {
        respawn_quota--;
        uint32_t start_edge = edge_dist(rec_gen);
        uint32_t target_edge = edge_dist(rec_gen);
        while (target_edge == start_edge)
          target_edge = edge_dist(rec_gen);

        agent_pool_.current_edge[i] = start_edge;
        agent_pool_.pos_meters[i] = 0.0f;

        // СТОП! Машина не должна двигаться, пока нет маршрута (Task: Fix
        // Respawn Loop)
        agent_pool_.velocity_mps[i] = 0.0f;

        float length = edge_lengths_cache_.empty()
                           ? router_manager_.get_edge_length(start_edge)
                           : edge_lengths_cache_[start_edge];
        agent_pool_.inv_edge_length_m[i] =
            (length > 0.001f) ? (1.0f / length) : 1.0f;

        // 2 = Состояние ожидания маршрута. Физика её не тронет.
        agent_pool_.is_active[i] = 2;
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
  if (!mpr_requests_buffer_.empty()) {
    // Разбронирование старых маршрутов — только в HandleResponses,
    // чтобы избежать double-unbook и underflow uint16_t.
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

      // Запрос завершен, снимаем флаг ожидания
      agent_pool_.is_waiting_route[r.agent_id] = 0;

      if (r.success) {
        const bool was_active = (agent_pool_.is_active[r.agent_id] == 1);

        // Verify that the agent is still on a valid segment of the calculated
        // path. If it has moved, but is still on one of the edges in the new
        // path, we align its progress index. Otherwise, if its current edge is
        // not found in the path, we discard it.
        int found_idx = -1;
        if (was_active && r.path_len > 0) {
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
            continue;
          }
        }

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

        // Reroute counter: agent already had a route and is getting a new one
        if (was_active)
          reroute_count_.fetch_add(1, std::memory_order_relaxed);
        else
          total_spawns_.fetch_add(1, std::memory_order_relaxed);

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
        if (!was_active && r.path_len > 0) {
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

        if (!was_active) {
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

          agent_pool_.is_active[r.agent_id] = 1;

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
        agent_pool_.is_active[r.agent_id] = 0;
      }
    }
  }
}

uint32_t TrafficEngine::GetActiveAgents() const {
  uint32_t active = 0;
  for (uint32_t i = 0; i < agent_pool_.is_active.size(); ++i) {
    if (agent_pool_.is_active[i])
      active++;
  }
  return active;
}

uint32_t TrafficEngine::GetDrivingAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.is_active.size(); ++i) {
    if (agent_pool_.is_active[i] == 1 && agent_pool_.is_waiting_route[i] == 0) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetReroutingAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.is_active.size(); ++i) {
    if (agent_pool_.is_active[i] == 1 && agent_pool_.is_waiting_route[i] == 1) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetWaitingSpawnAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.is_active.size(); ++i) {
    if (agent_pool_.is_active[i] == 2) {
      cnt++;
    }
  }
  return cnt;
}

uint32_t TrafficEngine::GetIdleAgents() const {
  uint32_t cnt = 0;
  for (uint32_t i = 0; i < agent_pool_.is_active.size(); ++i) {
    if (agent_pool_.is_active[i] == 0 && agent_pool_.is_waiting_route[i] == 0) {
      cnt++;
    }
  }
  return cnt;
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
