#pragma once
#include <cstdint>
#include <vector>
#include <string>

namespace traffic {

using NodeID = uint32_t;
using EdgeID = uint32_t;
using Weight = uint32_t; // Используем 32-битные веса для предотвращения переполнения в A*

constexpr Weight INF_WEIGHT = 0x7FFFFFFF; // Половина макса для безопасности сложения
constexpr NodeID INVALID_NODE = 0xFFFFFFFF;

struct RoutingResult {
    Weight total_weight = INF_WEIGHT;
    std::vector<NodeID> path;
};

// Структура для R-Tree (32 байта, половина кэш-линии)
#pragma pack(push, 1)
struct FlatBVHNode {
    float min_x, min_y, max_x, max_y;
    uint32_t left_child;
    uint32_t right_child;
    uint32_t node_id;
    uint32_t _padding;
};
#pragma pack(pop)

// Узел очереди с приоритетом (8 байт)
struct alignas(8) PQElement {
    Weight weight;
    NodeID id;
    bool operator>(const PQElement& other) const noexcept { return weight > other.weight; }
    bool operator<(const PQElement& other) const noexcept { return weight < other.weight; }
};

// Zero-overhead CSR View
struct GraphView {
    const uint32_t* row_ptr;
    const NodeID*   col_ind;
    const Weight*   weights;

    struct Edge {
        NodeID to;
        Weight w;
    };

    struct EdgeIterator {
        const NodeID* c;
        const Weight* w;
        inline Edge operator*() const noexcept { return {*c, *w}; }
        inline EdgeIterator& operator++() noexcept { ++c; ++w; return *this; }
        inline bool operator!=(const EdgeIterator& other) const noexcept { return c != other.c; }
    };

    struct EdgeRange {
        EdgeIterator b, e;
        inline EdgeIterator begin() const noexcept { return b; }
        inline EdgeIterator end() const noexcept { return e; }
    };

    [[nodiscard]] inline EdgeRange get_edges(NodeID u) const noexcept {
        uint32_t start = row_ptr[u];
        uint32_t end   = row_ptr[u + 1];
        return { {col_ind + start, weights + start}, {col_ind + end, weights + end} };
    }
};

} // namespace traffic
