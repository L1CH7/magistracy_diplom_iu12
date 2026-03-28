#pragma once

#include "types.hpp"
#include <vector>
#include <cassert>
#include <cstdint>

namespace traffic::router {

// In-Memory Прямой CSR Граф с принципами Zero-Cost OOP.
class CSRGraph {
private:
    std::vector<EdgeID> row_ptr_;
    std::vector<NodeID> col_ind_;
    
    // SoA (Structure of Arrays)
    std::vector<traffic::EdgeWeight> base_time_;
    std::vector<traffic::EdgeWeight> mpr_penalty_;
    std::vector<int32_t> k_magic_;
    
public:
    CSRGraph() = default;

    void init(PointCount num_nodes, EdgeID num_edges) {
        row_ptr_.resize(num_nodes + 1, 0);
        col_ind_.resize(num_edges, INVALID_NODE);
        base_time_.resize(num_edges, 0);
        mpr_penalty_.resize(num_edges, 0);
        k_magic_.resize(num_nodes, 0);
    }

    [[nodiscard]] inline PointCount num_nodes() const noexcept { return static_cast<PointCount>(row_ptr_.size() - 1); }
    [[nodiscard]] inline EdgeID num_edges() const noexcept { return static_cast<EdgeID>(col_ind_.size()); }

    [[nodiscard]] inline EdgeID begin_edge(NodeID u) const noexcept { return row_ptr_[u]; }
    [[nodiscard]] inline EdgeID end_edge(NodeID u) const noexcept { return row_ptr_[u + 1]; }

    [[nodiscard]] inline NodeID target(EdgeID e) const noexcept { return col_ind_[e]; }
    [[nodiscard]] inline traffic::EdgeWeight base_time(EdgeID e) const noexcept { return base_time_[e]; }
    
    [[nodiscard]] inline int32_t k_magic(NodeID u) const noexcept { return k_magic_[u]; }
    inline void set_k_magic(NodeID u, int32_t val) noexcept { k_magic_[u] = val; }

    [[nodiscard]] inline traffic::EdgeWeight mpr_penalty(EdgeID e) const noexcept { return mpr_penalty_[e]; }
    inline void set_mpr_penalty(EdgeID e, traffic::EdgeWeight penalty) noexcept { mpr_penalty_[e] = penalty; }

    // RAW Setters for Data Builder
    inline void set_row_ptr(NodeID u, EdgeID val) noexcept { row_ptr_[u] = val; }
    inline void set_col_ind(EdgeID e, NodeID val) noexcept { col_ind_[e] = val; }
    inline void set_base_time(EdgeID e, traffic::EdgeWeight val) noexcept { base_time_[e] = val; }

    // Range-based iteration support
    struct Edge {
        NodeID to;
        traffic::EdgeWeight w;
    };

    struct EdgeRange {
        const CSRGraph& graph;
        EdgeID start_idx;
        EdgeID end_idx;

        struct Iterator {
            const CSRGraph& graph;
            EdgeID curr;

            bool operator!=(const Iterator& other) const { return curr != other.curr; }
            void operator++() { ++curr; }
            Edge operator*() const {
                return { graph.target(curr), graph.base_time(curr) };
            }
        };

        Iterator begin() const { return { graph, start_idx }; }
        Iterator end() const { return { graph, end_idx }; }
    };

    [[nodiscard]] inline EdgeRange get_edges(NodeID u) const noexcept {
        return { *this, row_ptr_[u], row_ptr_[u + 1] };
    }
};

} // namespace traffic::router
