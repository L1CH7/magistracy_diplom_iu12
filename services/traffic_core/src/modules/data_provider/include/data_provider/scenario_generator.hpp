#pragma once

#include <cstdint>
#include <random>
#include <vector>

#include "common/net/messages.hpp"
#include "data_provider/agent_pool.hpp"

namespace traffic::data_provider {

/**
 * @brief Utility for populating the simulation with agents and initial route
 * requests. Designed for hardware-aligned benchmarks and scenario setup.
 */
class ScenarioGenerator {
public:
  /**
   * @brief Spawns a batch of agents with random start/target edges and
   * generates initial requests.
   * @param pool Destination agent pool.
   * @param count Number of agents to spawn.
   * @param max_edges Range of EdgeIDs to pick from [0, max_edges).
   * @param default_asf Availability Search Factor for initial requests.
   * @param initial_requests Output buffer for route requests to be sent to the
   * Router.
   */
  static void SpawnRandomAgents(
      AgentPool &pool, uint32_t count, uint32_t max_edges, uint16_t default_asf,
      std::vector<traffic::common::net::RouteRequest> &initial_requests,
      const std::vector<double> &wp_probs = {0.90, 0.05, 0.03, 0.02}) {
    // Zero-allocation setup: pre-allocate all SoA arrays in one go
    pool.Allocate(count);
    initial_requests.reserve(count);

    // Static PRNG to ensure continuity across calls in the same session
    static std::mt19937 gen{std::random_device{}()};
    std::uniform_int_distribution<uint32_t> dist(0, max_edges - 1);
    std::discrete_distribution<int> wp_dist(wp_probs.begin(), wp_probs.end());

    for (uint32_t i = 0; i < count; ++i) {
      uint8_t num_wp =
          static_cast<uint8_t>(wp_dist(gen)) + 2; // Returns 2, 3, 4, or 5
      pool.total_waypoints[i] = num_wp;
      pool.next_waypoint_idx[i] = 1; // 0 is start, 1 is next target

      std::vector<traffic::EdgeID> req_wps;
      req_wps.reserve(num_wp);

      for (int w = 0; w < num_wp; ++w) {
        traffic::EdgeID wp = dist(gen);
        // Simple distinct logic for consecutive waypoints
        if (w > 0) {
          while (wp == req_wps.back())
            wp = dist(gen);
        }
        pool.waypoints[i][w] = wp;
        req_wps.push_back(wp);
      }

      // Populate SoA (Structure of Arrays)
      pool.is_active[i] = 2; // 2 = Waiting for route
      pool.is_waiting_route[i] = 1;
      pool.route_epoch[i] = 1;

      pool.current_edge[i] = req_wps[0];
      pool.velocity_mps[i] = 15.0f; // Standard ~50 km/h
      pool.pos_meters[i] = 0.0f;
      pool.edge_enter_time_sec[i] = 0;
      pool.route_progress_idx[i] = 0;

      // Prepare Request POD for transmission
      traffic::common::net::RouteRequest req;
      req.agent_id = i;
      req.epoch = pool.route_epoch[i];
      req.num_waypoints = static_cast<uint8_t>(num_wp);
      for (uint8_t w = 0; w < req.num_waypoints; ++w) {
        req.waypoints[w] = req_wps[w];
      }
      req.asf = default_asf;
      req.current_time_sec = 0;

      initial_requests.push_back(std::move(req));
    }
  }
};

} // namespace traffic::data_provider
