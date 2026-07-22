#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>
#include <zmq.hpp>

#include <sstream>
#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

#include "common/logger.hpp"
#include "common/net/telemetry_protocol.hpp"
#include "core/telemetry_worker.hpp"
#include "core/traffic_engine.hpp"

using namespace traffic;

static std::atomic<bool> keep_running(true);

void signal_handler(int sig) {
  if (sig == SIGINT || sig == SIGTERM) {
    keep_running = false;
    LOG_INFO("Received shutdown signal...");
  }
}

int main(int argc, char **argv) {
  if (argc < 2) {
    std::cerr << "Usage: " << argv[0]
              << " <data_dir> [command_port] [telemetry_port]" << std::endl;
    return 1;
  }

  core::logging::init_logger();
  LOG_INFO("=== Traffic Core Daemon Starting ===");

#ifndef TOSTRING
#define STRINGIFY(x) #x
#define TOSTRING(x) STRINGIFY(x)
#endif

  // 1. Читаем Router Cores из ENV или CMake
#ifdef TRAFFIC_ROUTER_CORES
  std::string cores_str = TOSTRING(TRAFFIC_ROUTER_CORES);
  // Remove extra quotes if CMake passed them
  if (cores_str.size() >= 2 && cores_str.front() == '"' &&
      cores_str.back() == '"') {
    cores_str = cores_str.substr(1, cores_str.size() - 2);
  }
#else
  std::string cores_str = "2,8,3,9,4,10,5,11";
#endif

  if (const char *env_cores = std::getenv("TRAFFIC_ROUTER_CORES")) {
    cores_str = env_cores;
  }

  std::vector<int> router_cores;
  std::stringstream ss_cores(cores_str);
  std::string item;
  while (std::getline(ss_cores, item, ',')) {
    if (!item.empty())
      router_cores.push_back(std::stoi(item));
  }

  // 2. Читаем Sim Affinity из ENV или CMake
#ifdef TRAFFIC_SIM_AFFINITY
  int sim_affinity = TRAFFIC_SIM_AFFINITY;
#else
  int sim_affinity = 1;
#endif
  if (const char *env_sim = std::getenv("TRAFFIC_SIM_AFFINITY")) {
    sim_affinity = std::stoi(env_sim);
  }

  std::signal(SIGINT, signal_handler);
  std::signal(SIGTERM, signal_handler);

  std::string data_dir = argv[1];
  std::string cmd_addr = "tcp://*:5555";
  std::string pub_addr = "tcp://*:5556";

  if (argc >= 3)
    cmd_addr = "tcp://*:" + std::string(argv[2]);
  if (argc >= 4)
    pub_addr = "tcp://*:" + std::string(argv[3]);

  try {
    zmq::context_t context(1);

    // 2. Initialize Engine
    core::TrafficEngine engine(router_cores);
    auto init_status = engine.Init(data_dir);
    if (!init_status) {
      LOG_FATAL("Engine Init Failed: {}", init_status.error());
      return 1;
    }

    core::TelemetryWorker telemetry(context, 1000000); // 1M agents buffer
    telemetry.Start(pub_addr);
    engine.SetTelemetryWorker(&telemetry);

    // 3. Command Socket (REP)
    zmq::socket_t rep_socket(context, zmq::socket_type::rep);
    rep_socket.bind(cmd_addr);

    // Настройка таймаута сокета вместо dontwait-спиннинга
    int timeout_ms = 500;
    rep_socket.set(zmq::sockopt::rcvtimeo, timeout_ms);

    LOG_INFO("Daemon listening: CMD={} PUB={} SIM_CPU={}", cmd_addr, pub_addr,
             sim_affinity);

    std::thread engine_thread;
    std::atomic<bool> engine_running{false};

    while (keep_running) {
      zmq::message_t request_msg;
      auto res = rep_socket.recv(request_msg, zmq::recv_flags::none);

      if (!res) {
        continue; // Таймаут 500мс истек, проверяем keep_running и крутим снова
      }

      if (request_msg.size() < sizeof(common::net::CommandRequest)) {
        common::net::CommandAck ack{0, static_cast<uint8_t>(engine_running)};
        rep_socket.send(zmq::message_t(&ack, sizeof(ack)),
                        zmq::send_flags::none);
        continue;
      }

      auto *cmd =
          static_cast<const common::net::CommandRequest *>(request_msg.data());
      common::net::CommandAck ack{1, 0};

      switch (static_cast<common::net::CommandOpcode>(cmd->opcode)) {
      case common::net::CommandOpcode::STOP:
        LOG_INFO("Command: STOP");
        engine_running = false;
        if (engine_thread.joinable()) {
          engine_thread.join();
          LOG_INFO("Engine thread joined successfully.");
        }
        engine.ResetState();
        break;

      case common::net::CommandOpcode::START:
        if (engine_running) {
          LOG_WARN("START received while engine is running. Forcing stop...");
          engine_running = false;
          if (engine_thread.joinable())
            engine_thread.join();
          engine.ResetState();
        }

        LOG_INFO("Command: START agents={} asf={} accel={} fps={} chaos={} "
                 "respawn={}",
                 cmd->num_agents, cmd->asf, cmd->acceleration,
                 cmd->telemetry_fps, cmd->chaos_factor, cmd->respawn_enabled);

        engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps,
                             cmd->chaos_factor);
        engine.SetRespawn(cmd->respawn_enabled > 0);
        engine.PauseRouter(false);

        // If we already have agents, skip spawning to allow resuming warmup
        if (engine.GetActiveAgents() != cmd->num_agents ||
            engine.GetActiveAgents() == 0) {
          engine.SpawnAgents(cmd->num_agents, cmd->asf);
        }

        engine_running = true;
        engine_thread = std::thread([&engine, &engine_running, sim_affinity,
                                     num_agents = cmd->num_agents,
                                     &telemetry]() {
          auto centroid_cache =
              engine.GetRouterManager().BuildEdgeCentroidCache();
          auto last_heatmap_time = std::chrono::steady_clock::now();
          const auto heatmap_interval = std::chrono::milliseconds(1000);
#ifdef __linux__
          cpu_set_t cpuset_sim;
          CPU_ZERO(&cpuset_sim);
          CPU_SET(sim_affinity, &cpuset_sim);
          pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t),
                                 &cpuset_sim);
#endif
          uint32_t active = engine.GetActiveAgents();
          if (engine.GetRoutesComputed() < active) {
            LOG_INFO("Engine WARMING UP...");
            engine.Warmup(&engine_running);
            if (!engine_running) {
              LOG_INFO("Engine Warmup aborted");
              return;
            }
            LOG_INFO("Engine Warmed up. Active agents: {}",
                     engine.GetActiveAgents());
          } else {
            LOG_INFO("Engine already warmed up with {} agents, resuming...",
                     active);
          }

          // EMA buffer: сглаживает «рваность» live_volumes, визуально имитируя
          // распространение очереди
          const uint32_t hm_nodes = engine.GetRouterManager().num_nodes();
          std::vector<float> heatmap_smooth(hm_nodes, 0.0f);
          constexpr float HEATMAP_ALPHA = 0.1f;

          float dt = 5.0f;
          while (engine_running) {
            auto tick_start = std::chrono::steady_clock::now();

            float accel = engine.GetCurrentAcceleration();
            if (accel > 0.0f) {
              engine.Step(dt);
              engine.UpdateTelemetry();

              auto now = std::chrono::steady_clock::now();
              if (now - last_heatmap_time >= heatmap_interval) {
                last_heatmap_time = now;
                const uint32_t *live_volumes = engine.GetLiveVolumes();
                if (live_volumes) {
                  auto &rm = engine.GetRouterManager();

                  // EMA: decay previous + blend current live data
                  float peak_smooth = 0.0f;
                  for (uint32_t i = 0; i < hm_nodes; ++i) {
                    heatmap_smooth[i] =
                        HEATMAP_ALPHA * static_cast<float>(live_volumes[i]) +
                        (1.0f - HEATMAP_ALPHA) * heatmap_smooth[i];
                    if (heatmap_smooth[i] > peak_smooth)
                      peak_smooth = heatmap_smooth[i];
                  }

                  if (peak_smooth >= 0.5f) {
                    const uint32_t asf = engine.GetASF();

                    std::vector<common::net::HeatmapEntry> entries;
                    entries.reserve(hm_nodes / 50);

                    for (uint32_t edge_id = 0; edge_id < hm_nodes; ++edge_id) {
                      float agents_count = heatmap_smooth[edge_id];
                      if (agents_count < 0.1f)
                        continue;
                      const int64_t osm_id = rm.get_osm_id(edge_id);
                      if (osm_id <= 0)
                        continue;

                      float vis_cap_agents = std::max<float>(
                          1.0f,
                          static_cast<float>(rm.get_edge_capacity(edge_id)));
                      float jam_cap_agents = std::max<float>(
                          1.0f, static_cast<float>(
                                    rm.get_edge_physical_capacity(edge_id)));

                      if (jam_cap_agents < vis_cap_agents)
                        jam_cap_agents = vis_cap_agents + 1.0f;

                      float r = 0.0f;
                      if (agents_count <= vis_cap_agents) {
                        r = 0.01f;
                      } else if (agents_count >= jam_cap_agents) {
                        float over =
                            (agents_count - jam_cap_agents) / jam_cap_agents;
                        r = 1.0f + over;
                      } else {
                        float denom = jam_cap_agents - vis_cap_agents;
                        r = (agents_count - vis_cap_agents) / denom;
                        if (r < 0.01f)
                          r = 0.01f;
                      }

                      uint16_t true_cap = 1000;
                      uint16_t send_vol = static_cast<uint16_t>(std::min<float>(
                          std::max<float>(r * 1000.0f, 0.0f), 65535.0f));

                      entries.push_back(common::net::HeatmapEntry{
                          static_cast<uint64_t>(osm_id), send_vol, true_cap});
                    }
                    if (!entries.empty()) {
                      LOG_INFO("Heatmap: {} entries, peak_smooth_agents={:.2f}",
                               entries.size(), peak_smooth);
                      common::net::HeatmapHeader header{
                          2, 0, 0.0f, static_cast<uint32_t>(entries.size())};
                      telemetry.PublishHeatmap(
                          header,
                          std::span<const common::net::HeatmapEntry>(entries));
                    }
                  }
                }
              }

              auto tick_end = std::chrono::steady_clock::now();
              auto elapsed =
                  std::chrono::duration_cast<std::chrono::microseconds>(
                      tick_end - tick_start);
              auto target_micros =
                  static_cast<long long>((dt / accel) * 1000000.0f);
              if (elapsed.count() < target_micros) {
                std::this_thread::sleep_for(
                    std::chrono::microseconds(target_micros - elapsed.count()));
              }
            } else {
              // Paused
              std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
          }
        });
        break;
      case common::net::CommandOpcode::PAUSE:
        LOG_INFO("Command: PAUSE");
        engine_running = false;
        engine.PauseRouter(true);
        if (engine_thread.joinable()) {
          engine_thread.join();
          LOG_INFO("Engine thread joined successfully. Simulation paused.");
        }
        break;

      case common::net::CommandOpcode::RESUME:
        if (engine_running) {
          LOG_WARN("RESUME received while engine is running. Ignoring...");
          break;
        }

        LOG_INFO("Command: RESUME accel={} fps={} chaos={} respawn={}",
                 cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor,
                 cmd->respawn_enabled);

        engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps,
                             cmd->chaos_factor);
        engine.SetRespawn(cmd->respawn_enabled > 0);
        engine.PauseRouter(false);

        engine_running = true;
        engine_thread = std::thread([&engine, &engine_running, sim_affinity,
                                     &telemetry]() {
          auto centroid_cache =
              engine.GetRouterManager().BuildEdgeCentroidCache();
          auto last_heatmap_time = std::chrono::steady_clock::now();
          const auto heatmap_interval = std::chrono::milliseconds(1000);
#ifdef __linux__
          cpu_set_t cpuset_sim;
          CPU_ZERO(&cpuset_sim);
          CPU_SET(sim_affinity, &cpuset_sim);
          pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t),
                                 &cpuset_sim);
#endif
          uint32_t active = engine.GetActiveAgents();
          if (engine.GetRoutesComputed() < active) {
            LOG_INFO("Engine WARMING UP (Resumed)...");
            engine.Warmup(&engine_running);
            if (!engine_running) {
              LOG_INFO("Engine Warmup aborted");
              return;
            }
            LOG_INFO("Engine Warmed up. Active agents: {}", active);
          } else {
            LOG_INFO("Engine resuming with {} agents", active);
          }

          // EMA buffer для RESUME (идентично START блоку)
          const uint32_t hm_nodes_r = engine.GetRouterManager().num_nodes();
          std::vector<float> heatmap_smooth_r(hm_nodes_r, 0.0f);
          constexpr float HEATMAP_ALPHA_R = 0.1f;

          float dt = 5.0f;
          while (engine_running) {
            auto tick_start = std::chrono::steady_clock::now();

            float accel = engine.GetCurrentAcceleration();
            if (accel > 0.0f) {
              engine.Step(dt);
              engine.UpdateTelemetry();

              auto now = std::chrono::steady_clock::now();
              if (now - last_heatmap_time >= heatmap_interval) {
                last_heatmap_time = now;
                const uint32_t *live_volumes = engine.GetLiveVolumes();
                if (live_volumes) {
                  auto &rm = engine.GetRouterManager();

                  float peak_smooth_r = 0.0f;
                  for (uint32_t i = 0; i < hm_nodes_r; ++i) {
                    heatmap_smooth_r[i] =
                        HEATMAP_ALPHA_R * static_cast<float>(live_volumes[i]) +
                        (1.0f - HEATMAP_ALPHA_R) * heatmap_smooth_r[i];
                    if (heatmap_smooth_r[i] > peak_smooth_r)
                      peak_smooth_r = heatmap_smooth_r[i];
                  }

                  if (peak_smooth_r >= 0.5f) {
                    const auto *kmagic_ptr = rm.get_kmagic_ptr();
                    const auto *static_weights = rm.get_view().static_weights;
                    const uint32_t asf = engine.GetASF();

                    std::vector<common::net::HeatmapEntry> entries;
                    entries.reserve(hm_nodes_r / 50);

                    for (uint32_t edge_id = 0; edge_id < hm_nodes_r;
                         ++edge_id) {
                      float agents_count = heatmap_smooth_r[edge_id];
                      if (agents_count < 0.1f)
                        continue;
                      const int64_t osm_id = rm.get_osm_id(edge_id);
                      if (osm_id <= 0)
                        continue;

                      float vis_cap_agents = std::max<float>(
                          1.0f,
                          static_cast<float>(rm.get_edge_capacity(edge_id)));
                      float jam_cap_agents = std::max<float>(
                          1.0f, static_cast<float>(
                                    rm.get_edge_physical_capacity(edge_id)));

                      if (jam_cap_agents < vis_cap_agents)
                        jam_cap_agents = vis_cap_agents + 1.0f;

                      float r = 0.0f;
                      if (agents_count <= vis_cap_agents) {
                        r = agents_count / vis_cap_agents;
                      } else {
                        float denom = jam_cap_agents - vis_cap_agents;
                        float ratio_over =
                            (agents_count - vis_cap_agents) / denom;
                        r = 1.0f + ratio_over;
                      }

                      uint16_t true_cap = 1000;
                      uint16_t send_vol = static_cast<uint16_t>(std::min<float>(
                          std::max<float>(r * 1000.0f, 0.0f), 65535.0f));

                      entries.push_back(common::net::HeatmapEntry{
                          static_cast<uint64_t>(osm_id), send_vol, true_cap});
                    }
                    if (!entries.empty()) {
                      LOG_INFO("Heatmap(R): {} entries, peak_agents={:.2f}",
                               entries.size(), peak_smooth_r);
                      common::net::HeatmapHeader header{
                          2, 0, 0.0f, static_cast<uint32_t>(entries.size())};
                      telemetry.PublishHeatmap(
                          header,
                          std::span<const common::net::HeatmapEntry>(entries));
                    }
                  }
                }
              }

              auto tick_end = std::chrono::steady_clock::now();
              auto elapsed =
                  std::chrono::duration_cast<std::chrono::microseconds>(
                      tick_end - tick_start);
              auto target_micros =
                  static_cast<long long>((dt / accel) * 1000000.0f);
              if (elapsed.count() < target_micros) {
                std::this_thread::sleep_for(
                    std::chrono::microseconds(target_micros - elapsed.count()));
              }
            } else {
              std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
          }
        });
        break;

      case common::net::CommandOpcode::SET_SPEED:
        LOG_INFO("Command: SET_SPEED accel={} fps={} chaos={}",
                 cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor);
        engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps,
                             cmd->chaos_factor);
        break;

      case common::net::CommandOpcode::STEP:
        LOG_INFO("Command: STEP");
        engine.Step(0.1f);
        break;

      case common::net::CommandOpcode::STATS: {
        // For diagnostic purposes, return a JSON string instead of standard Ack
        auto counts = engine.GetAgentCounts();
        std::ostringstream json;
        json << "{";
        json << "\"sim_time\":" << engine.GetCurrentSimTime() << ",";
        json << "\"active_agents\":" << (counts.driving + counts.rerouting + counts.virtual_buffer) << ",";
        json << "\"agents_driving\":" << counts.driving << ",";
        json << "\"agents_rerouting\":" << counts.rerouting << ",";
        json << "\"agents_waiting_spawn\":" << counts.waiting_spawn << ",";
        json << "\"agents_idle\":" << counts.idle << ",";
        json << "\"waiting_in_queue_count\":" << counts.waiting_in_queue << ",";
        json << "\"virtual_buffer_count\":" << counts.virtual_buffer << ",";
        json << "\"teleported_jam_count\":" << engine.GetTeleportedJamCount() << ",";
        json << "\"traffic_flow_percent\":" << engine.GetTrafficFlowPercent() << ",";
        json << "\"total_spawns\":" << engine.GetTotalSpawns() << ",";
        json << "\"reroutes\":" << engine.GetTotalReroutes() << ",";
        json << "\"routes_computed\":" << engine.GetRoutesComputed() << ",";
        json << "\"routes_successful\":" << engine.GetTotalSuccessfulRoutes()
             << ",";
        json << "\"routes_discarded\":" << engine.GetTotalDiscardedRoutes()
             << ",";
        json << "\"routes_stale\":" << engine.GetTotalStaleRoutes() << ",";
        json << "\"routes_completed\":" << engine.GetTotalCompletedRoutes()
             << ",";
        json << "\"routes_failed\":" << engine.GetTotalFailedRoutes() << ",";
        json << "\"tti_global\":" << engine.GetTTI() << ",";
        json << "\"tti_samples\":" << engine.GetTTISampleCount() << ",";
        json << "\"current_accel\":" << engine.GetCurrentAcceleration() << ",";
        json << "\"router_load\":" << engine.GetRouterLoadFactor() << ",";
        json << "\"asf\":" << engine.GetASF() << ",";
        json << "\"num_buckets\":" << TRAFFIC_NUM_BUCKETS << ",";
        json << "\"slot_sec\":" << TRAFFIC_SLOT_SEC << ",";
        json << "\"bpr_enabled\":" << (engine.IsBPREnabled() ? "true" : "false")
             << ",";
        json << "\"profiling_enabled\":"
             << (engine.IsProfilingEnabled() ? "true" : "false") << ",";
        uint64_t profile_count = engine.GetProfiledRoutesCount();
        double visited_nodes_avg = 0.0;
        double route_cycles_avg = 0.0;
        if (profile_count > 0) {
          visited_nodes_avg =
              static_cast<double>(engine.GetTotalVisitedNodes()) /
              profile_count;
          route_cycles_avg =
              static_cast<double>(engine.GetTotalRouteCycles()) / profile_count;
          engine.ResetProfileCounters();
        }
        uint32_t route_time_max = engine.GetRouteTimeMaxUs();
        uint64_t route_time_sum = engine.GetRouteTimeSumUs();
        uint64_t route_time_cnt = engine.GetRouteTimeCount();
        double route_time_avg =
            (route_time_cnt > 0)
                ? (static_cast<double>(route_time_sum) / route_time_cnt)
                : 0.0;
        uint64_t router_wait_time = engine.GetRouterWaitTimeUs();

        // Reset counters for interval-based tracking in next poll
        engine.ResetRouteTimeCounters();
        engine.ResetTTICounters();

        json << "\"configured_agents\":" << engine.GetNumAgentsConfig() << ",";
        json << "\"visited_nodes_avg\":" << visited_nodes_avg << ",";
        json << "\"route_cycles_avg\":" << route_cycles_avg << ",";
        json << "\"route_time_max_us\":" << route_time_max << ",";
        json << "\"route_time_avg_us\":" << route_time_avg << ",";
        json << "\"router_wait_time_us\":" << router_wait_time;
        json << "}";
        std::string payload = json.str();
        rep_socket.send(zmq::message_t(payload.data(), payload.size()),
                        zmq::send_flags::none);
        continue; // Skip standard Ack
      }

      case common::net::CommandOpcode::ROUTE_ONE_OFF: {
        LOG_INFO("Command: ROUTE_ONE_OFF");
        if (request_msg.size() < sizeof(common::net::CommandRequest) +
                                     sizeof(common::net::OneOffRouteHeader)) {
          common::net::OneOffRouteResponseHeader err_header{0, 0, 0, 0.0f,
                                                            0.0f};
          rep_socket.send(zmq::message_t(&err_header, sizeof(err_header)),
                          zmq::send_flags::none);
          continue;
        }

        auto *route_header =
            reinterpret_cast<const common::net::OneOffRouteHeader *>(
                static_cast<const uint8_t *>(request_msg.data()) +
                sizeof(common::net::CommandRequest));

        uint32_t expected_size =
            sizeof(common::net::CommandRequest) +
            sizeof(common::net::OneOffRouteHeader) +
            route_header->num_waypoints * sizeof(common::net::PointCoord);

        if (request_msg.size() < expected_size) {
          common::net::OneOffRouteResponseHeader err_header{0, 0, 0, 0.0f,
                                                            0.0f};
          rep_socket.send(zmq::message_t(&err_header, sizeof(err_header)),
                          zmq::send_flags::none);
          continue;
        }

        const auto *points = reinterpret_cast<const common::net::PointCoord *>(
            static_cast<const uint8_t *>(request_msg.data()) +
            sizeof(common::net::CommandRequest) +
            sizeof(common::net::OneOffRouteHeader));

        std::vector<std::pair<float, float>> coords;
        coords.reserve(route_header->num_waypoints);
        for (int i = 0; i < route_header->num_waypoints; ++i) {
          coords.emplace_back(points[i].lon, points[i].lat);
        }

        LOG_DEBUG("Processing one-off route: {} waypoints", coords.size());

        // Use internal engine's RouterManager for simulation-aware routing
        // (baskets etc)
        auto &rm = engine.GetRouterManager();
        auto start_calc = std::chrono::steady_clock::now();
        auto result =
            rm.Route<true, false>(coords, route_header->start_time_sec);
        auto end_calc = std::chrono::steady_clock::now();
        float calc_ms =
            std::chrono::duration<float, std::milli>(end_calc - start_calc)
                .count();

        if (result) {
          LOG_INFO("Route found: {} edges, total_time={}s", result->path.size(),
                   result->total_weight);

          common::net::OneOffRouteResponseHeader res_header;
          res_header.success = 1;
          res_header.num_edges = static_cast<uint16_t>(result->path.size());
          res_header.total_distance_m = 0.0f; // Could be summed from edges
          res_header.total_time_sec = static_cast<float>(result->total_weight);
          res_header.calc_time_ms = calc_ms;

          std::vector<uint16_t> point_counts;
          std::vector<common::net::PointCoord> geometry;
          std::vector<float> etas;

          point_counts.reserve(result->path.size());
          geometry.reserve(result->path.size() * 5); // Estimate
          etas.reserve(result->path.size());

          for (size_t i = 0; i < result->path.size(); ++i) {
            auto edge_id = result->path[i];
            auto geom = rm.get_geometry_store()->get_geometry(edge_id);

            point_counts.push_back(static_cast<uint16_t>(geom.points.size()));
            for (const auto &pt : geom.points) {
              geometry.push_back(common::net::PointCoord{pt.x, pt.y});
            }
            etas.push_back(static_cast<float>(result->etas[i]));
            res_header.total_distance_m += geom.accum_lens.back();
          }
          res_header.total_points = static_cast<uint32_t>(geometry.size());

          // Send multi-frame response
          rep_socket.send(zmq::message_t(&res_header, sizeof(res_header)),
                          zmq::send_flags::sndmore);
          rep_socket.send(
              zmq::message_t(result->path.data(),
                             result->path.size() * sizeof(uint32_t)),
              zmq::send_flags::sndmore);
          rep_socket.send(
              zmq::message_t(etas.data(), etas.size() * sizeof(float)),
              zmq::send_flags::sndmore);
          rep_socket.send(
              zmq::message_t(point_counts.data(),
                             point_counts.size() * sizeof(uint16_t)),
              zmq::send_flags::sndmore);
          rep_socket.send(
              zmq::message_t(geometry.data(),
                             geometry.size() * sizeof(common::net::PointCoord)),
              zmq::send_flags::none);
        } else {
          common::net::OneOffRouteResponseHeader err_header{0, 0, 0, 0.0f,
                                                            0.0f};
          rep_socket.send(zmq::message_t(&err_header, sizeof(err_header)),
                          zmq::send_flags::none);
        }
        continue; // REP/REQ finished
      }

      default:
        ack.success = 0;
        break;
      }

      if (engine_running)
        ack.engine_state = 1;
      else if (engine.GetActiveAgents() > 0)
        ack.engine_state = 2; // PAUSED
      else
        ack.engine_state = 0; // IDLE
      rep_socket.send(zmq::message_t(&ack, sizeof(ack)), zmq::send_flags::none);
    }

    engine_running = false;
    engine.Stop();
    if (engine_thread.joinable())
      engine_thread.join();

    telemetry.Stop();
    LOG_INFO("Traffic Core Daemon stopped cleanly.");
  } catch (const std::exception &e) {
    LOG_FATAL("Daemon Exception: {}", e.what());
    return 1;
  }

  return 0;
}
