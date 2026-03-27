#pragma once

#include "types.hpp"
#include <vector>

namespace traffic::router {

// Обратный CSR Граф.
// Согласно архитектуре, необходим единожды (или очень редко) 
// для построения/инвалидации дерева кратчайших путей (эвристики) от Маяков (Landmarks)
// Во время горячего поиска (A*) НЕ используется и не нагружает L1-кэши.
class ReverseCSRGraph {
private:
    std::vector<EdgeID> row_ptr_;
    std::vector<NodeID> col_ind_;
    
    // Динамические веса/корзинки мы не храним! Эвристика ALT (Triangle Inequality)
    // обязуется быть Адмиссируемой (admissible) — она не должна ПРЕВЫШАТЬ реальный вес.
    // Поэтому предрасчет идет строго по минимальному Base Time в пустой сети.
    std::vector<Weight> base_time_; 

public:
    ReverseCSRGraph() = default;

    void init(size_t num_nodes, size_t num_edges) {
        row_ptr_.resize(num_nodes + 1, 0);
        col_ind_.resize(num_edges, INVALID_NODE);
        base_time_.resize(num_edges, 0);
    }

    [[nodiscard]] inline size_t num_nodes() const noexcept { return row_ptr_.size() - 1; }
    [[nodiscard]] inline size_t num_edges() const noexcept { return col_ind_.size(); }

    [[nodiscard]] inline EdgeID begin_edge(NodeID u) const noexcept { return row_ptr_[u]; }
    [[nodiscard]] inline EdgeID end_edge(NodeID u) const noexcept { return row_ptr_[u + 1]; }

    [[nodiscard]] inline NodeID source(EdgeID e) const noexcept { return col_ind_[e]; }
    [[nodiscard]] inline Weight base_time(EdgeID e) const noexcept { return base_time_[e]; }

    inline void set_row_ptr(NodeID u, EdgeID val) noexcept { row_ptr_[u] = val; }
    inline void set_col_ind(EdgeID e, NodeID val) noexcept { col_ind_[e] = val; }
    inline void set_base_time(EdgeID e, Weight val) noexcept { base_time_[e] = val; }
};

} // namespace traffic::router
