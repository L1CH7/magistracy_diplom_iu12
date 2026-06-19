#pragma once
#include <vector>
#include <limits>
#include <string>
#include <algorithm>
#include "common/graph_types.hpp"
#include "priority_queue.hpp"
#include <x86intrin.h>
#include "volume_bucket.hpp"

namespace traffic::router::compute {

/**
 * @brief Pure Dijkstra Router for monotonicity comparison with Radix Heaps.
 */
template<typename PriorityQueueType = PriorityQueue>
class DijkstraRouter {
public:
    explicit DijkstraRouter(traffic::GraphView view, traffic::NodeID max_nodes) 
        : view_(view) 
    {
        hot_states_.resize(max_nodes);
        cold_parents_.resize(max_nodes, traffic::INVALID_NODE);
        pq_.reserve(max_nodes);
    }

    template<bool TrafficEnabled, bool ProfileEnabled>
    [[nodiscard]] traffic::RoutingResult Route(
        traffic::NodeID source, 
        traffic::NodeID target, 
        traffic::AbsoluteTime start_time = 0,
        const VolumeBucket* buckets = nullptr,
        const traffic::PenaltyScale* k_magic_array = nullptr,
        const traffic::EdgeWeight* mpr_penalty_array = nullptr
    ) {
        traffic::RoutingResult result;
        result.path.reserve(1024);
        result.etas.reserve(1024);
        if (source == target) {
            result.total_weight = 0;
            result.path = {source};
            result.etas = {start_time};
            return result;
        }

        traffic::CpuCycles start_cycles = 0;
        if constexpr (ProfileEnabled) start_cycles = __rdtsc();

        uint32_t unique_visited_nodes = 0;
        current_visit_id_++;
        
        hot_states_[source].g_score = 0;
        hot_states_[source].visit_id = current_visit_id_;
        cold_parents_[source] = traffic::INVALID_NODE;
        
        pq_.clear();
        pq_.push({0, source});

        while (!pq_.empty()) {
            auto [g_curr, u] = pq_.pop();

            if (u == target) {
                if constexpr (ProfileEnabled) unique_visited_nodes++;
                break;
            }
            if (g_curr > hot_states_[u].g_score) continue;
            if constexpr (ProfileEnabled) unique_visited_nodes++;

            _mm_prefetch(reinterpret_cast<const char*>(&view_.row_ptr[u + 1]), _MM_HINT_T0);

            for (auto edge : view_.get_edges(u)) {
                traffic::NodeID v = edge.to;
                traffic::PathWeight w = edge.w;

                if constexpr (TrafficEnabled) {
                    traffic::AbsoluteTime arrival_time = start_time + g_curr;
                    uint32_t local_sec = arrival_time % traffic::router::compute::BUCKET_INTERVAL_SEC;
                    uint32_t t_idx = (arrival_time / traffic::router::compute::BUCKET_INTERVAL_SEC) % traffic::router::compute::NUM_BUCKETS;
                    uint32_t next_t_idx = (t_idx + 1) % traffic::router::compute::NUM_BUCKETS;

                    uint32_t v1 = buckets[v].volumes[t_idx].load(std::memory_order_relaxed);
                    uint32_t v2 = buckets[v].volumes[next_t_idx].load(std::memory_order_relaxed);

                    uint64_t scale = static_cast<uint64_t>(k_magic_array[v]);
                    uint64_t pen_1 = scale * v1 * v1;
                    uint64_t pen_2 = scale * v2 * v2;

                    uint32_t dynamic_penalty = static_cast<uint32_t>((pen_1 + ((pen_2 - pen_1) * local_sec) / traffic::router::compute::BUCKET_INTERVAL_SEC) >> 20);
                    if (dynamic_penalty > static_cast<uint32_t>(w) * 10) dynamic_penalty = w * 10;
                    w += dynamic_penalty + (mpr_penalty_array ? mpr_penalty_array[v] : 0);
                }

                traffic::PathWeight new_g = g_curr + w;
                if (hot_states_[v].visit_id != current_visit_id_ || new_g < hot_states_[v].g_score) {
                    hot_states_[v].g_score = new_g;
                    hot_states_[v].visit_id = current_visit_id_;
                    cold_parents_[v] = u;
                    pq_.push({new_g, v});
                }
            }
        }

        if constexpr (ProfileEnabled) {
            result.visited_nodes_count = unique_visited_nodes;
            result.route_cycles = __rdtsc() - start_cycles;
        }

        if (hot_states_[target].visit_id != current_visit_id_) {
            result.total_weight = traffic::INF_WEIGHT;
            return result;
        }

        result.total_weight = hot_states_[target].g_score;
        traffic::NodeID curr = target;
        while (curr != traffic::INVALID_NODE) {
            result.path.push_back(curr);
            result.etas.push_back(start_time + hot_states_[curr].g_score);
            curr = cold_parents_[curr];
        }
        std::reverse(result.path.begin(), result.path.end());
        std::reverse(result.etas.begin(), result.etas.end());
        return result;
    }

private:
    struct HotNodeState {
        traffic::PathWeight g_score  = traffic::INF_WEIGHT;
        traffic::PointCount visit_id = 0;
    };
    traffic::GraphView view_;
    std::vector<HotNodeState> hot_states_;
    std::vector<traffic::NodeID> cold_parents_;
    PriorityQueueType pq_;
    traffic::PointCount current_visit_id_ = 0;
};

} // namespace traffic::router::compute
