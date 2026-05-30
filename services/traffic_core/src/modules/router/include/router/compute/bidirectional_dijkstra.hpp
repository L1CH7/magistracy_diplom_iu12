#pragma once
#include <vector>
#include <limits>
#include <string>
#include <algorithm>
#include "common/graph_types.hpp"
#include "router/compute/priority_queue.hpp"
#include "router/compute/advanced_pqs.hpp"
#include <x86intrin.h>

namespace traffic::router::compute {

/**
 * @brief Bidirectional Dijkstra Router.
 * Builds a reverse graph transposition in memory at startup for O(1) backward steps.
 */
template<typename PriorityQueueType = Strict8ArySoAHeap>
class BiDijkstraRouter {
    struct ReverseEdge {
        traffic::NodeID from;
        traffic::PathWeight w;
    };

public:
    explicit BiDijkstraRouter(traffic::GraphView view, traffic::NodeID max_nodes) 
        : view_(view) 
    {
        // Build reverse graph transposition
        reverse_adj_.resize(max_nodes);
        for (traffic::NodeID u = 0; u < max_nodes; ++u) {
            for (auto edge : view_.get_edges(u)) {
                if (edge.to < max_nodes) {
                    reverse_adj_[edge.to].push_back({u, edge.w});
                }
            }
        }

        hot_states_f_.resize(max_nodes);
        hot_states_b_.resize(max_nodes);
        parents_f_.resize(max_nodes, traffic::INVALID_NODE);
        parents_b_.resize(max_nodes, traffic::INVALID_NODE);
        
        pq_f_.reserve(max_nodes);
        pq_b_.reserve(max_nodes);
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

        hot_states_f_[source].g_score = 0;
        hot_states_f_[source].visit_id = current_visit_id_;
        parents_f_[source] = traffic::INVALID_NODE;

        hot_states_b_[target].g_score = 0;
        hot_states_b_[target].visit_id = current_visit_id_;
        parents_b_[target] = traffic::INVALID_NODE;

        pq_f_.clear();
        pq_b_.clear();

        pq_f_.push({0, source});
        pq_b_.push({0, target});

        traffic::PathWeight best_w = traffic::INF_WEIGHT;
        traffic::NodeID meeting_node = traffic::INVALID_NODE;

        while (!pq_f_.empty() && !pq_b_.empty()) {
            // Forward step
            if (!pq_f_.empty()) {
                auto [g_curr, u] = pq_f_.pop();
                if constexpr (ProfileEnabled) pop_count++;

                if (g_curr > hot_states_f_[u].g_score) continue;
                if (g_curr >= best_w) break;

                for (auto edge : view_.get_edges(u)) {
                    traffic::NodeID v = edge.to;
                    traffic::PathWeight w = edge.w;

                    traffic::PathWeight new_g = g_curr + w;
                    if (hot_states_f_[v].visit_id != current_visit_id_ || new_g < hot_states_f_[v].g_score) {
                        hot_states_f_[v].g_score = new_g;
                        hot_states_f_[v].visit_id = current_visit_id_;
                        parents_f_[v] = u;
                        pq_f_.push({new_g, v});

                        // Check meeting
                        if (hot_states_b_[v].visit_id == current_visit_id_) {
                            traffic::PathWeight total_w = new_g + hot_states_b_[v].g_score;
                            if (total_w < best_w) {
                                best_w = total_w;
                                meeting_node = v;
                            }
                        }
                    }
                }
            }

            // Backward step
            if (!pq_b_.empty()) {
                auto [g_curr, u] = pq_b_.pop();
                if constexpr (ProfileEnabled) pop_count++;

                if (g_curr > hot_states_b_[u].g_score) continue;
                if (g_curr >= best_w) break;

                for (const auto& edge : reverse_adj_[u]) {
                    traffic::NodeID v = edge.from;
                    traffic::PathWeight w = edge.w;

                    traffic::PathWeight new_g = g_curr + w;
                    if (hot_states_b_[v].visit_id != current_visit_id_ || new_g < hot_states_b_[v].g_score) {
                        hot_states_b_[v].g_score = new_g;
                        hot_states_b_[v].visit_id = current_visit_id_;
                        parents_b_[v] = u;
                        pq_b_.push({new_g, v});

                        // Check meeting
                        if (hot_states_f_[v].visit_id == current_visit_id_) {
                            traffic::PathWeight total_w = new_g + hot_states_f_[v].g_score;
                            if (total_w < best_w) {
                                best_w = total_w;
                                meeting_node = v;
                            }
                        }
                    }
                }
            }
        }

        if constexpr (ProfileEnabled) {
            result.visited_nodes_count = pop_count;
            result.route_cycles = __rdtsc() - start_cycles;
        }

        if (meeting_node == traffic::INVALID_NODE || best_w == traffic::INF_WEIGHT) {
            result.total_weight = traffic::INF_WEIGHT;
            return result;
        }

        result.total_weight = best_w;

        // Reconstruct path
        // Forward part: from source to meeting_node
        std::vector<traffic::NodeID> forward_path;
        traffic::NodeID curr = meeting_node;
        while (curr != traffic::INVALID_NODE) {
            forward_path.push_back(curr);
            curr = parents_f_[curr];
        }
        std::reverse(forward_path.begin(), forward_path.end());

        // Backward part: from meeting_node to target
        std::vector<traffic::NodeID> backward_path;
        curr = parents_b_[meeting_node]; // Skip meeting_node to avoid duplicate
        while (curr != traffic::INVALID_NODE) {
            backward_path.push_back(curr);
            curr = parents_b_[curr];
        }

        result.path = std::move(forward_path);
        result.path.insert(result.path.end(), backward_path.begin(), backward_path.end());

        // Reconstruct ETAs
        result.etas.resize(result.path.size());
        if (!result.path.empty()) {
            result.etas[0] = start_time;
            for (size_t i = 1; i < result.path.size(); ++i) {
                // Approximate ETA based on forward/backward g_scores
                traffic::NodeID u = result.path[i];
                if (hot_states_f_[u].visit_id == current_visit_id_) {
                    result.etas[i] = start_time + hot_states_f_[u].g_score;
                } else {
                    result.etas[i] = start_time + (best_w - hot_states_b_[u].g_score);
                }
            }
        }

        return result;
    }

private:
    struct HotNodeState {
        traffic::PathWeight g_score  = traffic::INF_WEIGHT;
        traffic::PointCount visit_id = 0;
    };
    traffic::GraphView view_;
    std::vector<std::vector<ReverseEdge>> reverse_adj_;
    std::vector<HotNodeState> hot_states_f_;
    std::vector<HotNodeState> hot_states_b_;
    std::vector<traffic::NodeID> parents_f_;
    std::vector<traffic::NodeID> parents_b_;
    PriorityQueueType pq_f_;
    PriorityQueueType pq_b_;
    traffic::PointCount current_visit_id_ = 0;
};

} // namespace traffic::router::compute
