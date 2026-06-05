#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "common/net/messages.hpp"
#include "common/net/typed_endpoint.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/route_arena.hpp"

namespace traffic::decision_engine {

/**
 * @brief Management-by-Requirement (MPR) Engine.
 * Monitors agent progress and requests rerouting if significant delays are
 * detected. Designed for hardware-aligned zero-allocation hot cycles.
 */
class MprEngine {
public:
  explicit MprEngine() {
    // Pre-reserve buffers to avoid allocations in the hot loop
    stuck_indices_.reserve(1024);
  }

  /**
   * @brief Main MPR tick. Processes incoming routes and identifies agents
   * needing rerouting.
   * @param current_time_sec Simulation time.
   * @param pool Agent properties.
   * @param arena Route and ETA storage.
   * @param out_requests Buffer to fill with new reroute requests.
   */
  void Tick(uint32_t current_time_sec, data_provider::AgentPool &pool,
            data_provider::RouteArena &arena,
            std::vector<traffic::common::net::RouteRequest> &out_requests,
            int reroute_tokens) {
    // === PHASE 1: Hot Path Scan for delayed agents (AVX2-friendly) ===
    stuck_indices_.clear();
    const size_t agent_count = pool.Size();

    if (stuck_indices_.capacity() < agent_count) {
      stuck_indices_.reserve(agent_count);
    }

    if (last_route_request_time_.size() < agent_count) {
      last_route_request_time_.resize(agent_count, 0.0f);
    }
    if (last_route_request_edge_.size() < agent_count) {
      last_route_request_edge_.resize(agent_count, 0xFFFFFFFF);
    }

    const uint8_t *__restrict active = pool.is_active.data();
    const uint8_t *__restrict waiting = pool.is_waiting_route.data();
    const uint32_t *__restrict enter_times = pool.edge_enter_time_sec.data();
    const uint16_t *__restrict progress_idxs = pool.route_progress_idx.data();

    int tokens_left = reroute_tokens;

#pragma GCC ivdep
    for (size_t i = 0; i < agent_count; ++i) {
      // Only truly active agents
      if (active[i] == 1)
      {
        // If agent is already waiting in the queue, only proceed if it moved to a new edge
        if (waiting[i] == 1)
        {
          if (pool.current_edge[i] == last_route_request_edge_[i]) {
            continue; // Edge has not changed, do not duplicate/flood the queue
          }
        }

        const uint32_t elapsed = current_time_sec - enter_times[i];

        const auto etas = arena.GetEtas(static_cast<uint32_t>(i));
        if (etas.empty() || progress_idxs[i] + 1 >= etas.size())
          continue;

        const uint32_t current_eta = etas[progress_idxs[i]];
        const uint32_t next_eta = etas[progress_idxs[i] + 1];
        const uint32_t expected_duration =
            next_eta > current_eta ? (next_eta - current_eta) : 1;

        const uint32_t allowed_time =
            (expected_duration * TRAFFIC_MPR_TOLERANCE_NUM) /
            TRAFFIC_MPR_TOLERANCE_DEN;
            
        if (elapsed > allowed_time) {
          // Anti-Flood Check (30 sim-seconds cooldown for new queue placements)
          if (waiting[i] == 1 || (current_time_sec - last_route_request_time_[i] >= 30.0f)) {
            if (tokens_left > 0) {
              stuck_indices_.push_back(static_cast<uint32_t>(i));
              last_route_request_time_[i] = static_cast<float>(current_time_sec);
              tokens_left--;
            }
          }
        }
      }
    }

    // === PHASE 2: Prepare reroute requests ===
    for (uint32_t idx : stuck_indices_) {
      pool.is_waiting_route[idx] = 1;
      pool.route_epoch[idx]++;
      
      last_route_request_edge_[idx] = pool.current_edge[idx];

      traffic::common::net::RouteRequest req;
      req.agent_id = idx;
      req.epoch = pool.route_epoch[idx];
      req.asf = 1; // Default ASF for rerouting
      req.current_time_sec = current_time_sec;

      // Re-route from current position through all remaining waypoints
      req.waypoints[0] = pool.current_edge[idx];
      uint8_t wp_count = 1;

      for (uint8_t w = pool.next_waypoint_idx[idx];
           w < pool.total_waypoints[idx] && wp_count < 16; ++w) {
        req.waypoints[wp_count++] = pool.waypoints[idx][w];
      }
      req.num_waypoints = wp_count;

      out_requests.push_back(std::move(req));
    }
  }

private:
  // Reusable buffers to maintain Zero-Allocation status in the hot cycle
  std::vector<uint32_t> stuck_indices_;
  std::vector<float> last_route_request_time_;
  std::vector<uint32_t> last_route_request_edge_;
};

} // namespace traffic::decision_engine
