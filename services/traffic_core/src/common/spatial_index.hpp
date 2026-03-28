#pragma once

#include "common/graph_types.hpp"
#include <cmath>
#include <algorithm>
#include <utility>
#include <limits>

namespace traffic::common {

/**
 * @brief Пространственный индекс (R-Tree / BVH) для быстрого поиска ребер по координатам.
 * Использует плоскую структуру FlatBVHNode, оптимизированную для mmap.
 */
class SpatialIndex {
public:
    SpatialIndex(const FlatBVHNode* nodes, uint32_t num_nodes)
        : nodes_(nodes), num_nodes_(num_nodes) {}

    /**
     * @brief Находит ближайшее ребро и точку проекции на нем.
     * @param px Долгота (X)
     * @param py Широта (Y)
     * @return RoutePoint с ID ребра и смещением (0.0 - 1.0)
     */
    [[nodiscard]] RoutePoint MapToEdge(float px, float py) const noexcept {
        if (num_nodes_ == 0 || !nodes_) return {INVALID_NODE, 0.0f};

        float min_dist_sq = std::numeric_limits<float>::max();
        NodeID best_node_id = INVALID_NODE;
        float best_offset = 0.0f;

        // Стек для обхода дерева (фиксированный размер для исключения аллокаций)
        uint32_t stack[64];
        uint32_t stack_ptr = 0;
        stack[stack_ptr++] = 0; // Корень всегда в начале массива

        while (stack_ptr > 0) {
            uint32_t curr_idx = stack[--stack_ptr];
            const auto& node = nodes_[curr_idx];

            // 1. Прунинг: считаем минимальное расстояние от точки до BBox узла
            float dx = std::max({0.0f, node.min_x - px, px - node.max_x});
            float dy = std::max({0.0f, node.min_y - py, py - node.max_y});
            float bbox_dist_sq = dx * dx + dy * dy;

            // Если даже BBox дальше, чем уже найденная точка, скипаем всю ветку
            if (bbox_dist_sq >= min_dist_sq) continue;

            if (node.node_id != INVALID_NODE) {
                // Лист: выполняем расчет проекции. 
                // ВАЖНО: Пока нет геометрии всех точек ребра, считаем проекцию на диагональ BBox.
                auto [dist_sq, offset] = ProjectPointOnSegment(px, py, node.min_x, node.min_y, node.max_x, node.max_y);
                if (dist_sq < min_dist_sq) {
                    min_dist_sq = dist_sq;
                    best_node_id = node.node_id;
                    best_offset = offset;
                }
            } else {
                // Внутренний узел: добавляем дочерние элементы в стек
                // Для ускорения можно было бы сначала класть в стек более далекого ребенка,
                // чтобы первым обрабатывать более близкого (эвристика), но для плоского обхода достаточно и так.
                if (node.left_child != 0xFFFFFFFF) stack[stack_ptr++] = node.left_child;
                if (node.right_child != 0xFFFFFFFF) stack[stack_ptr++] = node.right_child;
            }
        }

        return {best_node_id, best_offset};
    }

private:
    /**
     * @brief Проекция точки P на отрезок AB.
     * @return Пара {квадрат расстояния до проекции, нормализованное смещение t [0,1]}
     */
    [[nodiscard]] static inline std::pair<float, float> ProjectPointOnSegment(
        float px, float py, float ax, float ay, float bx, float by) noexcept {
        
        float l2 = (bx - ax)*(bx - ax) + (by - ay)*(by - ay);
        if (l2 == 0.0f) return {(px - ax)*(px - ax) + (py - ay)*(py - ay), 0.0f};
        
        // Находим параметр t проекции точки на прямую, ограниченный отрезком [0,1]
        float t = std::max(0.0f, std::min(1.0f, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2));
        
        float proj_x = ax + t * (bx - ax);
        float proj_y = ay + t * (by - ay);
        
        float dx = px - proj_x;
        float dy = py - proj_y;
        return {dx * dx + dy * dy, t};
    }

    const FlatBVHNode* nodes_ = nullptr;
    uint32_t num_nodes_ = 0;
};

} // namespace traffic::common
