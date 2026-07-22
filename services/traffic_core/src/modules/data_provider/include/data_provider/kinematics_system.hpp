#pragma once

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "agent_pool.hpp"
#include "common/graph_types.hpp"
#include "deadlock_mitigation_system.hpp"
#include "physics_context.hpp"
#include "route_arena.hpp"

namespace traffic::data_provider {

/**
 * @brief Computes the effective velocity for an agent entering an edge.
 * Mirrors the BPR logic in TdAltRouter hot-path exactly.
 * Called ONCE at edge entry, not every tick.
 * @param edge_id  The edge the agent is entering.
 * @param ctx      Physics context (buckets, k_magic, static weights, lengths).
 * @param length_m Physical length of the edge in meters.
 * @return Effective velocity in m/s.
 */
[[nodiscard]] inline float ComputeEdgeEntrySpeed(traffic::EdgeID edge_id,
                                                 const PhysicsContext &ctx,
                                                 float length_m) noexcept {
  if (length_m < 0.1f)
    length_m = 0.1f;

  // w = static free-flow weight in seconds.
  // Matches TdAltRouter: the CSR `w` IS the free-flow travel time.
  float w = (ctx.static_weights)
                ? static_cast<float>(ctx.static_weights[edge_id])
                : (length_m / 15.0f); // fallback: assume 15 m/s free-flow

  if (w < 0.001f)
    w = 0.001f; // guard zero-weight edges

  if (ctx.live_volumes && ctx.k_magic) {
    uint32_t current_vol = ctx.live_volumes[edge_id];
    uint64_t scale = static_cast<uint64_t>(ctx.k_magic[edge_id]);

    // Penalty computation: scale by ASF because agents represent multiple cars
    uint64_t scaled_vol = static_cast<uint64_t>(current_vol) * ctx.asf;
    uint32_t penalty =
        static_cast<uint32_t>((scale * scaled_vol * scaled_vol) >> 20);

    // Cap at 10x free-flow, same as TdAltRouter
    // Use float to avoid zero-cap for short edges (w < 1s)
    const float max_penalty = w * 10.0f;
    if (static_cast<float>(penalty) > max_penalty)
      penalty = static_cast<uint32_t>(max_penalty);

    w += static_cast<float>(penalty);
  }

  return length_m / w;
}

/**
 * @brief Candidate for edge transition sorting.
 */
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
      : pool_(pool), arena_(arena), mitigation_system_(pool, arena) {}

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

    // Делегируем процесс буфера SUMO и разгрузки заторов отдельному модулю
    mitigation_system_.Process(dt, ctx);

    float *__restrict pos = pool_.pos_meters.data();
    float *__restrict vel = pool_.velocity_mps.data();
    const AgentStatus *__restrict status = pool_.status.data();
    const traffic::EdgeID *__restrict current_edges = pool_.current_edge.data();
    const float *__restrict inv_len = pool_.inv_edge_length_m.data();

    for (size_t agent_idx = 0; agent_idx < agent_count; ++agent_idx) {
      if (status[agent_idx] == AgentStatus::INACTIVE ||
          status[agent_idx] == AgentStatus::VIRTUAL_BUFFER) {
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

      float queue_length_m = static_cast<float>(queue_size) *
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
        if (live_vol > vis_cap && live_vol > 0) {
          float C_vis_agents =
              std::max<float>(1.0f, static_cast<float>(vis_cap));
          v_discharge =
              v_free_mps * (C_vis_agents / static_cast<float>(live_vol));
        }
      }
      if (v_discharge < 1.3f)
        v_discharge = 1.3f; // Минимальная скорость выползания из пробки

      float agent_speed = v_free_mps;

      // 3. Кинематика (Двухрежимная)
      if (!pool_.in_queue[agent_idx] && pos[agent_idx] < stop_line_m - 1.0f) {
        // РЕЖИМ 1: Свободный поток. Агент далеко от пробки, едет на V_free.
        if (pool_.status[agent_idx] == AgentStatus::ACTIVE_QUEUE) {
          // Агент вышел из пробки — сбрасываем флаг очереди.
          pool_.in_queue[agent_idx] = 0;
          if (ctx.queue_volumes) {
            uint32_t q = ctx.queue_volumes[current_edge].load(std::memory_order_relaxed);
            if (q > 0) ctx.queue_volumes[current_edge].fetch_sub(1, std::memory_order_relaxed);
          }
          pool_.status[agent_idx] = AgentStatus::ACTIVE_FREE_FLOW;
        }
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
      if (pool_.IsDriving(i) && __builtin_expect(pos[i] * inv_len[i] >= 1.0f, 0)) {
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
   * @return Number of agents that completed their route this tick.
   */
  uint32_t ProcessTransitions(const PhysicsContext &ctx) {
    uint32_t completed_agents = 0;
    for (uint32_t agent_idx : pool_.transition_queue) {
      bool blocked = false;
      // --- Multi-hop loop ---
      // With large acceleration (dt >> edge_length/velocity), an agent can
      // overshoot multiple edges in a single tick. We drain the overshoot here
      // in one call rather than wasting N ticks on N hops at 1 hop/tick.
      while (pool_.IsDriving(agent_idx) &&
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

        if (route.empty()) {
          // Агент доехал до конца стартового ребра до ответа роутера.
          // Фиксируем на конце ребра до получения пути (не деспавним!)
          pool_.route_progress_idx[agent_idx]--;
          pool_.pos_meters[agent_idx] = edge_len;
          pool_.velocity_mps[agent_idx] = 0.0f;
          blocked = true;
          break;
        }

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

          // 1. Проверка физической емкости следующего ребра
          if( __builtin_expect( load_next + 1 > jam_cap_next, 0 ) )
          {
              // Блокировка перехода: следующий сегмент забит.
              // Откатываем индекс маршрута, фиксируем агента строго на конце текущего ребра (без откатов назад)
              pool_.route_progress_idx[agent_idx]--;
              pool_.pos_meters[agent_idx] = edge_len; // На самой границе ребра
              pool_.velocity_mps[agent_idx] = 0.0f;   // Остановка в очереди

              // Регистрируем агента в очереди обратного распространения затора (Queue Spillback)
              if( pool_.status[agent_idx] != AgentStatus::ACTIVE_QUEUE )
              {
                  pool_.status[agent_idx] = AgentStatus::ACTIVE_QUEUE;
                  pool_.spillback_start_time_sec[agent_idx] = ctx.current_time_sec;
                  pool_.spillback_wait_queue.push_back( agent_idx );
              }
              // queue_volumes уже учтён при первом входе (стр. 188)

              blocked = true;
              break; // Прекращаем попытки перехода в текущем такте
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
          pool_.status[agent_idx] = AgentStatus::ACTIVE_FREE_FLOW;

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

          pool_.status[agent_idx] = AgentStatus::INACTIVE;
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
      if (pool_.IsDriving(agent_idx) && !blocked) {
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
  DeadlockMitigationSystem mitigation_system_;
};

} // namespace traffic::data_provider
