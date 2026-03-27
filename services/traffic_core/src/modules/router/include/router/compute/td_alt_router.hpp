#pragma once
#include <vector>
#include <limits>
#include <string>
#include <algorithm>
#include "common/graph_types.hpp"
#include "priority_queue.hpp"
#include "alt_heuristics.hpp"

namespace traffic::router {

class ALTHeuristicModule {
public:
    void set_landmarks(const uint16_t* ptr) { landmarks_ptr_ = ptr; }
    const uint16_t* get_landmark_ptr() const { return landmarks_ptr_; }

private:
    const uint16_t* landmarks_ptr_ = nullptr;
};

/**
 * @brief NodeState holds dynamic search data. 
 * Aligned to 64 bytes for cache efficiency.
 */
struct alignas(64) NodeState {
    traffic::PathWeight g_score      = traffic::INF_WEIGHT;
    traffic::NodeID     parent_node  = traffic::INVALID_NODE;
    uint32_t            visit_id     = 0;
};

class TdAltRouter {
public:
    explicit TdAltRouter(traffic::GraphView view, uint32_t max_nodes) 
        : view_(view) 
    {
        node_states_.resize(max_nodes);
        pq_.reserve(2048);
    }

    ALTHeuristicModule& get_heuristic() { return heuristic_module_; }

    [[nodiscard]] traffic::RoutingResult find_path(traffic::NodeID source, traffic::NodeID target) {
        if (source == target) {
            traffic::RoutingResult res;
            res.total_weight = 0;
            res.path = {source};
            return res;
        }
        
        const uint16_t* landmarks = heuristic_module_.get_landmark_ptr();
        const uint16_t* target_l_ptr = (landmarks && target != traffic::INVALID_NODE) ? 
                                       (landmarks + (target * TRAFFIC_TOTAL_LANDMARKS * 2)) : nullptr;
        
        ALTHeuristic alt;
        current_visit_id_++;
        
        node_states_[source].g_score = 0;
        node_states_[source].visit_id = current_visit_id_;
        node_states_[source].parent_node = traffic::INVALID_NODE;
        
        pq_.clear();
        pq_.push({0, source});

        while (!pq_.empty()) {
            auto [f_curr, u] = pq_.pop();

            if (u == target) break;

            // f_curr > g + h
            traffic::PathWeight g_u = node_states_[u].g_score;
            traffic::PathWeight h_u = (landmarks && target_l_ptr) ? alt.get_heuristic_avx2(landmarks + (u * TRAFFIC_TOTAL_LANDMARKS * 2), target_l_ptr) : 0;
            
            if (f_curr > g_u + h_u) continue;

            for (auto edge : view_.get_edges(u)) {
                traffic::NodeID v = edge.to;
                traffic::PathWeight w = edge.w;
                
                traffic::PathWeight new_g = g_u + w;

                if (node_states_[v].visit_id != current_visit_id_ || new_g < node_states_[v].g_score) {
                    node_states_[v].g_score = new_g;
                    node_states_[v].parent_node = u;
                    node_states_[v].visit_id = current_visit_id_;

                    traffic::PathWeight h_v = (landmarks && target_l_ptr) ? 
                                       alt.get_heuristic_avx2(landmarks + (v * TRAFFIC_TOTAL_LANDMARKS * 2), target_l_ptr) : 0;
                    pq_.push({new_g + h_v, v});
                }
            }
        }

        if (node_states_[target].visit_id != current_visit_id_) {
            return {traffic::INF_WEIGHT, {}};
        }

        traffic::RoutingResult result;
        result.total_weight = node_states_[target].g_score;
        
        traffic::NodeID curr = target;
        while (curr != traffic::INVALID_NODE) {
            result.path.push_back(curr);
            curr = node_states_[curr].parent_node;
        }
        std::reverse(result.path.begin(), result.path.end());
        return result;
    }

private:
    traffic::GraphView view_;
    ALTHeuristicModule heuristic_module_;
    std::vector<NodeState> node_states_;
    PriorityQueue pq_;
    uint32_t current_visit_id_ = 0;
};

} // namespace traffic::router
