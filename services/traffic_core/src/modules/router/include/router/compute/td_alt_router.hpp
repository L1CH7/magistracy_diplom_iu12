#pragma once
#include <vector>
#include <limits>
#include <string>
#include <algorithm>
#include "common/graph_types.hpp"
#include "priority_queue.hpp"
#include "alt_heuristics.hpp"
#include <x86intrin.h>
#include "volume_bucket.hpp"
namespace traffic::router::compute {

static constexpr uint32_t DEFAULT_PQ_CAPACITY = 2048;
static constexpr uint32_t VALUES_PER_LANDMARK = 2; // to_L and from_L

class ALTHeuristicModule {
public:
    void set_landmarks(const traffic::EdgeWeight* ptr) { landmarks_ptr_ = ptr; }
    const traffic::EdgeWeight* get_landmark_ptr() const { return landmarks_ptr_; }

private:
    const traffic::EdgeWeight* landmarks_ptr_ = nullptr;
};

/**
 * @brief NodeState holds dynamic search data. 
 * Aligned to 64 bytes for cache efficiency.
 */
struct alignas(64) NodeState {
    traffic::PathWeight g_score      = traffic::INF_WEIGHT;
    traffic::NodeID     parent_node  = traffic::INVALID_NODE;
    traffic::PointCount visit_id     = 0;
};

class TdAltRouter {
public:
    explicit TdAltRouter(traffic::GraphView view, traffic::NodeID max_nodes) 
        : view_(view) 
    {
        node_states_.resize(max_nodes);
        pq_.reserve(DEFAULT_PQ_CAPACITY);
    }

    ALTHeuristicModule& get_heuristic() { return heuristic_module_; }

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
        if (source == target) {
            result.total_weight = 0;
            result.path = {source};
            result.etas = {start_time};
            return result;
        }

        traffic::CpuCycles start_cycles = 0;
        if constexpr (ProfileEnabled) start_cycles = __rdtsc();

        uint32_t pop_count = 0;
        const traffic::EdgeWeight* landmarks = heuristic_module_.get_landmark_ptr();
        const traffic::EdgeWeight* target_l_ptr = (landmarks && target != traffic::INVALID_NODE) ?
            (landmarks + (target * TRAFFIC_TOTAL_LANDMARKS * VALUES_PER_LANDMARK)) : nullptr;
        
        ALTHeuristic alt;
        current_visit_id_++;
        
        node_states_[source].g_score = 0;
        node_states_[source].visit_id = current_visit_id_;
        node_states_[source].parent_node = traffic::INVALID_NODE;
        
        pq_.clear();
        pq_.push({0, source});

        while (!pq_.empty()) {
            auto [f_curr, u] = pq_.pop();
            if constexpr (ProfileEnabled) pop_count++;

            if (u == target) break;

            traffic::PathWeight g_u = node_states_[u].g_score;
            traffic::PathWeight h_u = (landmarks && target_l_ptr) ?
                alt.get_heuristic_avx2(landmarks + (u * TRAFFIC_TOTAL_LANDMARKS * VALUES_PER_LANDMARK), target_l_ptr) : 0;
            if (f_curr > g_u + h_u) continue;

            _mm_prefetch(reinterpret_cast<const char*>(&view_.row_ptr[u + 1]), _MM_HINT_T0);

            for (auto edge : view_.get_edges(u)) {
                traffic::NodeID v = edge.to;
                traffic::PathWeight w = edge.w;

                // Zero-cost ветвление на этапе компиляции
                if constexpr (TrafficEnabled) {
                    traffic::AbsoluteTime arrival_time = start_time + g_u;
                    uint32_t local_sec = arrival_time % traffic::router::compute::BUCKET_INTERVAL_SEC;
                    uint32_t t_idx = (arrival_time / traffic::router::compute::BUCKET_INTERVAL_SEC) % traffic::router::compute::NUM_BUCKETS;
                    uint32_t next_t_idx = (t_idx + 1) % traffic::router::compute::NUM_BUCKETS;

                    // Relaxed memory order для скорости
                    uint32_t v1 = buckets[v].volumes[t_idx].load(std::memory_order_relaxed);
                    uint32_t v2 = buckets[v].volumes[next_t_idx].load(std::memory_order_relaxed);

                    uint64_t scale = static_cast<uint64_t>(k_magic_array[v]);
                    uint64_t pen_1 = scale * v1 * v1;
                    uint64_t pen_2 = scale * v2 * v2;

                    uint32_t dynamic_penalty = static_cast<uint32_t>((pen_1 + ((pen_2 - pen_1) * local_sec) / traffic::router::compute::BUCKET_INTERVAL_SEC) >> 20);
                    
                    if (dynamic_penalty > static_cast<uint32_t>(w) * 10) dynamic_penalty = w * 10;
                    
                    w += dynamic_penalty + (mpr_penalty_array ? mpr_penalty_array[v] : 0);
                }

                traffic::PathWeight new_g = g_u + w;
                if (node_states_[v].visit_id != current_visit_id_ || new_g < node_states_[v].g_score) {
                    node_states_[v].g_score = new_g;
                    node_states_[v].parent_node = u;
                    node_states_[v].visit_id = current_visit_id_;
                    
                    traffic::PathWeight h_v = (landmarks && target_l_ptr) ?
                        alt.get_heuristic_avx2(reinterpret_cast<const uint16_t*>(landmarks + (v * TRAFFIC_TOTAL_LANDMARKS * VALUES_PER_LANDMARK)), reinterpret_cast<const uint16_t*>(target_l_ptr)) : 0;
                    pq_.push({new_g + h_v, v});
                }
            }
        }

        if constexpr (ProfileEnabled) {
            result.visited_nodes_count = pop_count;
            result.route_cycles = __rdtsc() - start_cycles;
        }

        if (node_states_[target].visit_id != current_visit_id_) {
            result.total_weight = traffic::INF_WEIGHT;
            return result;
        }

        result.total_weight = node_states_[target].g_score;
        traffic::NodeID curr = target;
        
        while (curr != traffic::INVALID_NODE) {
            result.path.push_back(curr);
            result.etas.push_back(start_time + node_states_[curr].g_score);
            curr = node_states_[curr].parent_node;
        }
        std::reverse(result.path.begin(), result.path.end());
        std::reverse(result.etas.begin(), result.etas.end());
        
        return result;
    }

    [[nodiscard]] traffic::NodeID num_nodes() const noexcept { return static_cast<traffic::NodeID>(node_states_.size()); }

private:
    traffic::GraphView view_;
    ALTHeuristicModule heuristic_module_;
    std::vector<NodeState> node_states_;
    PriorityQueue pq_;
    traffic::PointCount current_visit_id_ = 0;
};

} // namespace traffic::router::compute
