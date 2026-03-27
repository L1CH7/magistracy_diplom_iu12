#pragma once

#include "common/graph_types.hpp"
#include <vector>
#include <cassert>
#include <cstdint>

namespace traffic::router {

// In-Memory Прямой CSR Граф с принципами Zero-Cost OOP.
class CSRGraph {
private:
    std::vector<traffic::EdgeID> row_ptr_;
    std::vector<traffic::NodeID> col_ind_;
    
    // SoA (Structure of Arrays)
    std::vector<traffic::Weight> base_time_;
    std::vector<traffic::Weight> mpr_penalty_;
    std::vector<int32_t> k_magic_;
    
public:
    CSRGraph() = default;

    void init(size_t num_nodes, size_t num_edges) {
        row_ptr_.resize(num_nodes + 1, 0);
        col_ind_.resize(num_edges, traffic::INVALID_NODE);
        base_time_.resize(num_edges, 0);
        mpr_penalty_.resize(num_edges, 0);
        k_magic_.resize(num_nodes, 0);
    }

    [[nodiscard]] inline size_t num_nodes() const noexcept { return row_ptr_.size() - 1; }
    [[nodiscard]] inline size_t num_edges() const noexcept { return col_ind_.size(); }

    [[nodiscard]] inline traffic::EdgeID begin_edge(traffic::NodeID u) const noexcept { return row_ptr_[u]; }
    [[nodiscard]] inline traffic::EdgeID end_edge(traffic::NodeID u) const noexcept { return row_ptr_[u + 1]; }

    [[nodiscard]] inline traffic::NodeID target(traffic::EdgeID e) const noexcept { return col_ind_[e]; }
    [[nodiscard]] inline traffic::Weight base_time(traffic::EdgeID e) const noexcept { return base_time_[e]; }
    
    [[nodiscard]] inline int32_t k_magic(traffic::NodeID u) const noexcept { return k_magic_[u]; }
    inline void set_k_magic(traffic::NodeID u, int32_t val) noexcept { k_magic_[u] = val; }

    [[nodiscard]] inline traffic::Weight mpr_penalty(traffic::EdgeID e) const noexcept { return mpr_penalty_[e]; }
    inline void set_mpr_penalty(traffic::EdgeID e, traffic::Weight penalty) noexcept { mpr_penalty_[e] = penalty; }

    // RAW Setters for Data Builder
    inline void set_row_ptr(traffic::NodeID u, traffic::EdgeID val) noexcept { row_ptr_[u] = val; }
    inline void set_col_ind(traffic::EdgeID e, traffic::NodeID val) noexcept { col_ind_[e] = val; }
    inline void set_base_time(traffic::EdgeID e, traffic::Weight val) noexcept { base_time_[e] = val; }

    // Range-based iteration support
    struct Edge {
        traffic::NodeID to;
        traffic::Weight w;
    };

    struct EdgeRange {
        const CSRGraph& graph;
        traffic::EdgeID start_idx;
        traffic::EdgeID end_idx;

        struct Iterator {
            const CSRGraph& graph;
            traffic::EdgeID curr;

            bool operator!=(const Iterator& other) const { return curr != other.curr; }
            void operator++() { ++curr; }
            Edge operator*() const {
                return { graph.target(curr), graph.base_time(curr) };
            }
        };

        Iterator begin() const { return { graph, start_idx }; }
        Iterator end() const { return { graph, end_idx }; }
    };

    [[nodiscard]] inline EdgeRange get_edges(traffic::NodeID u) const noexcept {
        return { *this, row_ptr_[u], row_ptr_[u + 1] };
    }
};

} // namespace traffic::router
