#pragma once
#include <cstdint>
#include <vector>
#include <string>

namespace traffic {

using NodeID = uint32_t;
using EdgeID = uint32_t;
using BVHNodeID = uint32_t;
using PointCount = uint32_t;
using EdgeWeight = uint16_t; // Вес одного сегмента (в CSR) - 2 байта
using PathWeight = uint32_t; // Накопленный вес маршрута (g_score) - 4 байта
using SegmentOffset = float; // Доля пройденного пути по ребру (0.0f - 1.0f)

// Строгие алиасы для DOD
using AbsoluteTime = uint32_t;  // Секунды от начала симуляции (или 00:00)
using VolumeCount  = uint16_t;  // Количество машин в корзинке
using CpuCycles    = uint64_t;  // Аппаратные такты (RDTSC)
using PenaltyScale = uint32_t;  // Коэффициент масштабирования штрафа затора

constexpr PathWeight INF_WEIGHT = 0xFFFFFFFF;
constexpr NodeID INVALID_NODE = 0xFFFFFFFF;
constexpr BVHNodeID INVALID_BVH_NODE = 0xFFFFFFFF;

struct RoutingResult {
    PathWeight total_weight = INF_WEIGHT;
    uint32_t visited_nodes_count = 0; 
    CpuCycles route_cycles = 0; 
    
    std::vector<NodeID> path;
    std::vector<AbsoluteTime> etas; // Абсолютное время входа на каждое ребро
};

// Точка маршрута (привязка к конкретному ребру и смещение на нем)
struct RoutePoint { 
    EdgeID edge_id; 
    SegmentOffset offset; 
};

// Финальный ответ роутера
struct RouteResponse { 
    uint32_t total_time = 0;     // Итоговое время маршрута
    float total_length_m = 0.0f; // Физическая длина маршрута в метрах
    uint32_t total_visited_nodes = 0; // Итоговое количество посещенных узлов A*
    CpuCycles total_cycles = 0;   // Итоговое количество тактов CPU
    
    std::vector<EdgeID> path; // Последовательность ID ребер
    std::vector<AbsoluteTime> etas; // Время прибытия на каждое ребро
};

#pragma pack(push, 1)
struct ExtendedAttributes {
    float speed_kmh;          // 4 bytes
    uint8_t lanes;            // 1 byte
    uint8_t highway_class;    // 1 byte
    uint8_t oneway;           // 1 byte
    uint8_t pad;              // 1 byte
    float length_m;           // 4 bytes
    float t_free_base;        // 4 bytes
    int32_t k_magic;          // 4 bytes
    float min_x;              // 4 bytes
    float min_y;              // 4 bytes
    uint16_t visual_capacity; // 2 bytes
    uint16_t jam_capacity;    // 2 bytes
};
#pragma pack(pop)
static_assert(sizeof(ExtendedAttributes) == 32, "ExtendedAttributes must be exactly 32 bytes!");

// Структура для R-Tree (32 байта, половина кэш-линии)
#pragma pack(push, 1)
struct FlatBVHNode {
    float min_x, min_y, max_x, max_y;
    BVHNodeID left_child;
    BVHNodeID right_child;
    EdgeID node_id; // Store EdgeID in leaf nodes
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
    const EdgeID*     row_ptr;
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
        const uint32_t start = row_ptr[u];
        const uint32_t end   = row_ptr[u + 1];
        return { {col_ind + start, static_weights + start}, {col_ind + end, static_weights + end} };
    }
};

} // namespace traffic
