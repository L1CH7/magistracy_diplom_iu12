#pragma once
#include <vector>
#include <limits>
#include <string>
#include <algorithm>
#include <cmath>
#include "common/graph_types.hpp"
#include "common/geometry_store.hpp"
#include "router/compute/priority_queue.hpp"
#include "router/compute/advanced_pqs.hpp"
#include "graph_builder/road_config.hpp" // For GeometryStore if needed
#include "common/geometry_store.hpp"
#include <x86intrin.h>

namespace traffic::router::compute {

/**
 * @brief A* Router using Euclidean distance heuristic on edge-based graph.
 */
template<typename PriorityQueueType = Strict8ArySoAHeap>
class AStarRouter {
public:
    explicit AStarRouter(traffic::GraphView view, traffic::NodeID max_nodes, const void* geom_store = nullptr) 
        : view_(view), geom_store_(geom_store)
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
        const void* buckets = nullptr,
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

        uint32_t pop_count = 0;
        current_visit_id_++;
        
        traffic::PathWeight h_source = GetHeuristic(source, target);
        hot_states_[source].g_score = 0;
        hot_states_[source].h_score = h_source;
        hot_states_[source].visit_id = current_visit_id_;
        cold_parents_[source] = traffic::INVALID_NODE;
        
        pq_.clear();
        pq_.push({h_source, source});

        while (!pq_.empty()) {
            auto [f_curr, u] = pq_.pop();
            if constexpr (ProfileEnabled) pop_count++;

            if (u == target) break;
            
            traffic::PathWeight g_u = hot_states_[u].g_score;
            traffic::PathWeight h_u = hot_states_[u].h_score;
            if (f_curr > g_u + h_u) continue;

            _mm_prefetch(reinterpret_cast<const char*>(&view_.row_ptr[u + 1]), _MM_HINT_T0);

            for (auto edge : view_.get_edges(u)) {
                traffic::NodeID v = edge.to;
                traffic::PathWeight w = edge.w;

                traffic::PathWeight new_g = g_u + w;
                if (hot_states_[v].visit_id != current_visit_id_ || new_g < hot_states_[v].g_score) {
                    traffic::PathWeight h_v = GetHeuristic(v, target);
                    hot_states_[v].g_score = new_g;
                    hot_states_[v].h_score = h_v;
                    hot_states_[v].visit_id = current_visit_id_;
                    cold_parents_[v] = u;
                    pq_.push({new_g + h_v, v});
                }
            }
        }

        if constexpr (ProfileEnabled) {
            result.visited_nodes_count = pop_count;
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
    // Helper to calculate Euclidean heuristic in meters / 36.0 (max speed 130 km/h)
    traffic::PathWeight GetHeuristic(traffic::NodeID u, traffic::NodeID target) const noexcept {
        if (!geom_store_) return 0;
        
        // We use dynamic casting or manual offset because common::GeometryStore is a C++ type
        // Let's assume it's common::GeometryStore
        const auto* gs = static_cast<const traffic::common::GeometryStore*>(geom_store_);
        auto geom_u = gs->get_geometry(u);
        auto geom_t = gs->get_geometry(target);
        if (geom_u.points.empty() || geom_t.points.empty()) return 0;
        
        float lon1 = geom_u.points[0].x;
        float lat1 = geom_u.points[0].y;
        float lon2 = geom_t.points[0].x;
        float lat2 = geom_t.points[0].y;
        
        float dy = (lat1 - lat2) * 111320.0f;
        float dx = (lon1 - lon2) * 62560.0f;
        float dist_m = std::sqrt(dx * dx + dy * dy);
        
        // Stronger heuristic: div by 15.0 m/s (54 km/h) to approximate real urban speeds
        return static_cast<traffic::PathWeight>(dist_m / 15.0f);
    }

    struct HotNodeState {
        traffic::PathWeight g_score  = traffic::INF_WEIGHT;
        traffic::PathWeight h_score  = 0;
        traffic::PointCount visit_id = 0;
    };
    traffic::GraphView view_;
    const void* geom_store_;
    std::vector<HotNodeState> hot_states_;
    std::vector<traffic::NodeID> cold_parents_;
    PriorityQueueType pq_;
    traffic::PointCount current_visit_id_ = 0;
};

} // namespace traffic::router::compute
