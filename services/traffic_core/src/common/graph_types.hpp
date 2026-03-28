#pragma once
#include <cstdint>
#include <vector>
#include <string>

namespace traffic {

using NodeID = uint32_t;
using EdgeID = uint32_t;
using EdgeWeight = uint16_t; // Вес одного сегмента (в CSR) - 2 байта
using PathWeight = uint32_t; // Накопленный вес маршрута (g_score) - 4 байта

constexpr PathWeight INF_WEIGHT = 0xFFFFFFFF;
constexpr NodeID INVALID_NODE = 0xFFFFFFFF;

struct RoutingResult {
    PathWeight total_weight = INF_WEIGHT;
    std::vector<NodeID> path;
};

// Точка маршрута (привязка к конкретному ребру и смещение на нем)
struct RoutePoint { 
    NodeID edge_id; 
    float offset; // Доля пройденного пути по ребру (от 0.0f до 1.0f)
};

// Финальный ответ роутера
struct RouteResponse { 
    uint32_t total_time;     // Итоговое время маршрута
    std::vector<NodeID> path; // Последовательность ID ребер
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
    PathWeight weight;
    NodeID id;
    bool operator>(const PQElement& other) const noexcept { return weight > other.weight; }
    bool operator<(const PQElement& other) const noexcept { return weight < other.weight; }
};

// Zero-overhead CSR View
struct GraphView {
    const uint32_t*   row_ptr;
    const NodeID*     col_ind;
    const EdgeWeight* static_weights;

    struct Edge {
        NodeID to;
        PathWeight w; // При чтении кастим uint16_t -> uint32_t (Zero-Cost)
    };

    struct EdgeIterator {
        const NodeID*     c;
        const EdgeWeight* w;
        
        inline Edge operator*() const noexcept { 
            return { *c, static_cast<PathWeight>(*w) }; 
        }
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
        return { {col_ind + start, static_weights + start}, {col_ind + end, static_weights + end} };
    }
};

} // namespace traffic
