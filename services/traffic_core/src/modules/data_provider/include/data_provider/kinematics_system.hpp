#pragma once

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "agent_pool.hpp"
#include "common/graph_types.hpp"
#include "route_arena.hpp"

namespace traffic::data_provider {

/**
 * @brief Lightweight context for physics calculations at edge transitions.
 * All pointers are non-owning. Passed by value into ProcessTransitions.
 */
struct PhysicsContext {
  // Live physical occupancy data (updated by KinematicsSystem during
  // transitions)
  uint32_t *live_volumes = nullptr;
  uint32_t *max_volumes = nullptr;
  std::atomic<uint32_t> *queue_volumes = nullptr;
  const traffic::PenaltyScale *k_magic = nullptr;

  // Static edge weights from the CSR graph (w_i = free-flow travel time in
  // seconds). Indexed directly by EdgeID. Non-owning ptr into mmap'd region.
  const traffic::EdgeWeight *static_weights = nullptr;

  // Precomputed per-edge physical lengths in meters, indexed by EdgeID.
  // nullptr = fallback to length / 15 m/s
  const float *edge_lengths_m = nullptr;

  // Pointer to mmap'd ExtendedAttributes array
  const ExtendedAttributes *edge_attributes = nullptr;

  uint32_t current_time_sec = 0;
  uint16_t asf = 1;
  std::vector<uint32_t> *completed_agents_out = nullptr;
};


struct TransitionCandidate {
  uint32_t agent_idx;
  uint32_t edge_id;
  float pos;

  bool operator<(const TransitionCandidate &other) const noexcept {
    if (edge_id != other.edge_id) {
      return edge_id < other.edge_id;
    }
    return pos > other.pos; // Сортировка по убыванию позиции (для FIFO)
  }
};

/**
 * @brief Zero-overhead simulation engine.
 * Implements hardware-optimized kinematic updates and topological transitions.
 */
class KinematicsSystem {
public:
  KinematicsSystem(AgentPool &pool, RouteArena &arena)
      : pool_(pool), arena_(arena) {}

  inline uint32_t FastRand() noexcept {
    xorshift_state_ ^= xorshift_state_ << 13;
    xorshift_state_ ^= xorshift_state_ >> 17;
    xorshift_state_ ^= xorshift_state_ << 5;
    return xorshift_state_;
  }

  inline float FastRandFloat() noexcept {
    return (FastRand() & 0xFFFFFF) / 16777216.0f;
  }

  /**
   * @brief Updates position for all active agents.
   * Uses SIMD-friendly loops and precalculated inverse lengths to maximize
   * throughput.
   * @param dt Elapsed time in seconds.
   */
  void AdvanceKinematics(float dt, const PhysicsContext &ctx = {}) noexcept {
    const size_t agent_count = pool_.Size();
    if (agent_count == 0) {
      return;
    }

    float *__restrict pos = pool_.pos_meters.data();
    float *__restrict vel = pool_.velocity_mps.data();
    const uint8_t *__restrict active = pool_.is_active.data();
    const traffic::EdgeID *__restrict current_edges = pool_.current_edge.data();
    const float *__restrict inv_len = pool_.inv_edge_length_m.data();

    for (size_t agent_idx = 0; agent_idx < agent_count; ++agent_idx) {
      if (active[agent_idx] != 1) {
        continue;
      }

      traffic::EdgeID current_edge = current_edges[agent_idx];
      float edge_len = 1.0f / inv_len[agent_idx];

      // 1. Вычисляем длину физической очереди на ребре в пространстве агентов
      // (Agent Space)
      uint32_t queue_size = 0;
      if (ctx.queue_volumes) {
        queue_size =
            ctx.queue_volumes[current_edge].load(std::memory_order_relaxed);
      }

      uint8_t lanes = 1;
      if (ctx.edge_attributes) {
        lanes = ctx.edge_attributes[current_edge].lanes;
        if (lanes == 0)
          lanes = 1;
      }

      float queue_length_m = static_cast<float>(queue_size * ctx.asf) *
                             static_cast<float>(TRAFFIC_CAR_LENGTH_M) /
                             static_cast<float>(lanes);

      // 2. Виртуальная стоп-линия (хвост пробки)
      float stop_line_m = std::max(0.0f, edge_len - queue_length_m);

      // Определяем v_free_mps и v_discharge
      float w = 0.0f;
      if (ctx.edge_attributes) {
        w = ctx.edge_attributes[current_edge].t_free_base;
      } else if (ctx.static_weights) {
        w = static_cast<float>(ctx.static_weights[current_edge]);
      } else {
        w = edge_len / 15.0f;
      }
      if (w < 0.001f)
        w = 0.001f;
      float v_free_mps = edge_len / w;

      // v_discharge = v_free * (C_vis / V_live)
      float v_discharge = v_free_mps;
      if (ctx.edge_attributes && ctx.live_volumes) {
        uint32_t vis_cap = ctx.edge_attributes[current_edge].visual_capacity;
        uint32_t live_vol = ctx.live_volumes[current_edge];
        uint32_t live_vol_cars = live_vol * ctx.asf;
        if (live_vol_cars > vis_cap && live_vol > 0) {
          float C_vis_cars = std::max<float>(1.0f, static_cast<float>(vis_cap));
          v_discharge =
              v_free_mps * (C_vis_cars / static_cast<float>(live_vol_cars));
        }
      }
      if (v_discharge < 1.3f)
        v_discharge = 1.3f; // Минимальная скорость выползания из пробки

      float agent_speed = v_free_mps;

      // 3. Кинематика (Двухрежимная)
      if (!pool_.in_queue[agent_idx] && pos[agent_idx] < stop_line_m - 1.0f) {
        // РЕЖИМ 1: Свободный поток. Агент далеко от пробки, едет на V_free.
        agent_speed = v_free_mps;

        // Двигаем агента
        float new_pos = pos[agent_idx] + agent_speed * dt;

        // Если агент доехал до хвоста пробки в этом тике - он вступает в
        // очередь
        if (new_pos >= stop_line_m) {
          pos[agent_idx] = stop_line_m;  // Упирается в хвост
          pool_.in_queue[agent_idx] = 1; // Помечаем, что агент вошел в пробку
          if (ctx.queue_volumes) {
            ctx.queue_volumes[current_edge].fetch_add(
                1, std::memory_order_relaxed);
          }
          vel[agent_idx] = v_discharge; // Задаем discharge скорость
        } else {
          pos[agent_idx] = new_pos;
          vel[agent_idx] = agent_speed;
        }
      } else {
        // РЕЖИМ 2: Очередь. Агент уже в пробке.
        agent_speed = v_discharge;

        // В очереди агент медленно ползет к финишу со скоростью вытекания
        pos[agent_idx] += agent_speed * dt;
        vel[agent_idx] = agent_speed;
      }
    }

    // --- COLD PATH FILTER: Identify agents crossing the edge boundary ---
    pool_.transition_queue.clear();

    thread_local std::vector<TransitionCandidate> candidates;
    if (__builtin_expect(candidates.capacity() < agent_count / 10, 0)) {
      candidates.reserve(agent_count / 10);
    }
    candidates.clear();

    for (size_t i = 0; i < agent_count; ++i) {
      if (active[i] == 1 && __builtin_expect(pos[i] * inv_len[i] >= 1.0f, 0)) {
        candidates.emplace_back(TransitionCandidate{static_cast<uint32_t>(i),
                                                    current_edges[i], pos[i]});
      }
    }

    if (!candidates.empty()) {
      std::sort(candidates.begin(), candidates.end());
      for (const auto &c : candidates) {
        pool_.transition_queue.push_back(c.agent_idx);
      }
    }
  }

  /**
   * @brief Processes topological transitions for agents in the queue.
   *
   * Key fix vs previous version:
   *  - inv_edge_length_m is now updated immediately when agent enters next
   * edge.
   *  - BPR velocity is computed ONCE at edge entry (O(transitions), not
   * O(agents*ticks)).
   *
   * - [x] Update `kinematics_system.hpp`
   * - [x] Add `max_volumes` to `PhysicsContext` struct
   * - [x] Update peak volumes in `ProcessTransitions()` during edge hops
   *
   * @param ctx Physics context for BPR speed and geometry lookup.
   * @param dt  Elapsed time in seconds (used for leak probability).
   * @return Number of agents that completed their route this tick.
   */
  uint32_t ProcessTransitions(const PhysicsContext &ctx, float dt = 0.1f) {
    uint32_t completed_agents = 0;
    for (uint32_t agent_idx : pool_.transition_queue) {
      bool blocked = false;
      // --- Multi-hop loop ---
      // With large acceleration (dt >> edge_length/velocity), an agent can
      // overshoot multiple edges in a single tick. We drain the overshoot here
      // in one call rather than wasting N ticks on N hops at 1 hop/tick.
      while (pool_.is_active[agent_idx] == 1 &&
             pool_.pos_meters[agent_idx] * pool_.inv_edge_length_m[agent_idx] >=
                 1.0f) {
        // Subtract the current edge length to correct the overshoot
        float edge_len = 1.0f / pool_.inv_edge_length_m[agent_idx];
        pool_.pos_meters[agent_idx] -= edge_len;
        if (pool_.pos_meters[agent_idx] < 0.0f)
          pool_.pos_meters[agent_idx] = 0.0f;

        uint16_t next_idx = ++pool_.route_progress_idx[agent_idx];
        auto route = arena_.GetRoute(agent_idx);
        traffic::EdgeID old_edge = pool_.current_edge[agent_idx];

        if (next_idx < route.size()) {
          traffic::EdgeID next_edge = route[next_idx];

          // Prefetch attributes and volumes of the subsequent edge in the route
          if (next_idx + 1 < route.size()) {
            traffic::EdgeID lookahead_edge = route[next_idx + 1];
            if (ctx.edge_attributes) {
              __builtin_prefetch(&ctx.edge_attributes[lookahead_edge], 0, 3);
            }
            if (ctx.live_volumes) {
              __builtin_prefetch(&ctx.live_volumes[lookahead_edge], 1, 3);
            }
          }

          uint32_t jam_cap_next = 1;
          uint32_t jam_cap_curr = 1;

          if (ctx.edge_attributes) {
            jam_cap_next = std::max<uint32_t>(
                1, ctx.edge_attributes[next_edge].jam_capacity);
            jam_cap_curr = std::max<uint32_t>(
                1, ctx.edge_attributes[old_edge].jam_capacity);
          }

          uint32_t load_next =
              ctx.live_volumes ? ctx.live_volumes[next_edge] : 0;
          uint32_t load_curr =
              ctx.live_volumes ? ctx.live_volumes[old_edge] : 0;

          // 1. Check if next edge is congested (even for 1 more agent)
          // Always allow transition if the next edge is empty (load_next == 0)
          uint32_t load_next_cars = load_next * ctx.asf;
          if (load_next > 0 && __builtin_expect(load_next_cars + ctx.asf > jam_cap_next, 0)) {
            bool blocked_transition = true;

            // 2. Absolute limit in cars (150% of physical capacity)
            uint32_t absolute_max_cars =
                jam_cap_next + std::max<uint32_t>(1, jam_cap_next / 2);

            if (load_next_cars + ctx.asf <= absolute_max_cars) {
              // 3. Pressure is calculated strictly in agents using integer cross-multiplication (asf cancels out):
              // load_curr / jam_cap_curr >= load_next / jam_cap_next
              if (static_cast<uint64_t>(load_curr) * jam_cap_next >=
                  static_cast<uint64_t>(load_next) * jam_cap_curr) {
                float next_len = 25.0f; // fallback
                if (ctx.edge_attributes) {
                  next_len = ctx.edge_attributes[next_edge].length_m;
                }
                uint32_t leak_chance = (next_len < 20.0f) ? 15 : 5;
                if ((FastRand() % 100) < leak_chance) {
                  blocked_transition = false; // Successfully squeezed through!
                }
              }

              // Защита от вечного gridlock'a: если всё же заблокированы, даем шанс просочиться
              if (blocked_transition) {
                 float leak_prob = (static_cast<float>(jam_cap_next) * 0.01f * dt) / static_cast<float>(ctx.asf);
                 if (FastRandFloat() < leak_prob) {
                     blocked_transition = false;
                 }
              }
            } else {
               // ЖЕСТКИЙ БЛОК. Больше абсолютного максимума машин не пускаем ни при каких условиях.
               blocked_transition = true;
            }

            if (blocked_transition) {
              // Rollback transition. Agent remains at the very end of the
              // current edge
              pool_.route_progress_idx[agent_idx]--;
              pool_.pos_meters[agent_idx] =
                  edge_len - 0.05f;                 // 5 cm from the boundary
              pool_.velocity_mps[agent_idx] = 0.0f; // Stopped in queue
              blocked = true;
              break; // Stop transitioning this agent
            }
          }

          // Check if we reached a waypoint
          if (pool_.next_waypoint_idx[agent_idx] <
                  pool_.total_waypoints[agent_idx] &&
              next_edge ==
                  pool_.waypoints[agent_idx]
                                 [pool_.next_waypoint_idx[agent_idx]]) {
            pool_.next_waypoint_idx[agent_idx]++;
          }

          // Update physical occupancy counters
          if (ctx.live_volumes) {
            if (ctx.live_volumes[old_edge] > 0)
              ctx.live_volumes[old_edge]--;
            ctx.live_volumes[next_edge]++;
            if (ctx.max_volumes &&
                ctx.live_volumes[next_edge] > ctx.max_volumes[next_edge])
              ctx.max_volumes[next_edge] = ctx.live_volumes[next_edge];
          }
          if (ctx.queue_volumes) {
            uint32_t q_vol =
                ctx.queue_volumes[old_edge].load(std::memory_order_relaxed);
            if (q_vol > 0) {
              ctx.queue_volumes[old_edge].fetch_sub(1,
                                                    std::memory_order_relaxed);
            }
          }

          pool_.current_edge[agent_idx] = next_edge;
          pool_.edge_enter_time_sec[agent_idx] = ctx.current_time_sec;
          pool_.in_queue[agent_idx] = 0;

          // Update geometry immediately so the while-condition re-evaluates
          // correctly
          float len =
              (ctx.edge_lengths_m) ? ctx.edge_lengths_m[next_edge] : 1.0f;
          if (len < 0.1f)
            len = 0.1f;
          pool_.inv_edge_length_m[agent_idx] = 1.0f / len;
        } else {
          // End of route: despawn and update occupancy
          if (ctx.live_volumes) {
            if (ctx.live_volumes[old_edge] > 0)
              ctx.live_volumes[old_edge]--;
          }
          if (ctx.queue_volumes) {
            uint32_t q_vol =
                ctx.queue_volumes[old_edge].load(std::memory_order_relaxed);
            if (q_vol > 0) {
              ctx.queue_volumes[old_edge].fetch_sub(1,
                                                    std::memory_order_relaxed);
            }
          }

          pool_.is_active[agent_idx] = 0;
          pool_.is_waiting_route[agent_idx] = 0;
          pool_.pos_meters[agent_idx] = 0.0f;
          pool_.in_queue[agent_idx] = 0;
          completed_agents++;
          if (ctx.completed_agents_out) {
            ctx.completed_agents_out->push_back(agent_idx);
          }
        }
      }

      // Compute static Free-Flow speed ONCE for the edge the agent will
      // actually dwell on. Intermediate edges (passed through during multi-hop)
      // are irrelevant.
      if (pool_.is_active[agent_idx] == 1 && !blocked) {
        traffic::EdgeID curr_edge = pool_.current_edge[agent_idx];
        float len = (ctx.edge_lengths_m)
                        ? ctx.edge_lengths_m[curr_edge]
                        : (1.0f / pool_.inv_edge_length_m[agent_idx]);
        float w = 0.0f;
        if (ctx.edge_attributes) {
          w = ctx.edge_attributes[curr_edge].t_free_base;
        } else if (ctx.static_weights) {
          w = static_cast<float>(ctx.static_weights[curr_edge]);
        } else {
          w = len / 15.0f;
        }
        if (w < 0.001f)
          w = 0.001f;
        pool_.velocity_mps[agent_idx] = len / w;
      }
    }
    return completed_agents;
  }

private:
  AgentPool &pool_;
  RouteArena &arena_;
  uint32_t xorshift_state_ = 123456789;
};

} // namespace traffic::data_provider
