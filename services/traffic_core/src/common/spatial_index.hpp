#pragma once

#include "geometry_store.hpp"
#include "graph_types.hpp"
#include <iostream>
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace traffic::common {

/**
 * @brief Пространственный индекс (R-Tree / BVH) для быстрого поиска ребер по
 * координатам. Использует плоскую структуру FlatBVHNode, оптимизированную для
 * mmap.
 */
class SpatialIndex {
public:
  SpatialIndex(const FlatBVHNode *nodes, traffic::PointCount num_nodes,
               const GeometryStore *geom_store)
      : nodes_(nodes), num_nodes_(num_nodes), geom_store_(geom_store) {}

  /**
   * @brief Находит ближайшее ребро и точку проекции на нем.
   * @param px Долгота (X)
   * @param py Широта (Y)
   * @return RoutePoint с ID ребра и смещением (0.0 - 1.0)
   */
  [[nodiscard]] traffic::RoutePoint MapToEdge(float px, float py) const noexcept {
    if (num_nodes_ == 0 || !nodes_) {
      std::cerr << "[SpatialIndex] ERROR: index is empty or null!\n";
      return {traffic::INVALID_NODE, 0.0f};
    }

    float min_dist_sq = std::numeric_limits<float>::max();
    traffic::EdgeID best_node_id = traffic::INVALID_NODE;
    traffic::SegmentOffset best_offset = 0.0f;

    // Стек для обхода дерева (фиксированный размер)
    static constexpr size_t MAX_STACK_SIZE = 512;
    traffic::BVHNodeID stack[MAX_STACK_SIZE];
    uint32_t stack_ptr = 0;
    stack[stack_ptr++] = 0;

    while (stack_ptr > 0) {
      traffic::BVHNodeID curr_idx = stack[--stack_ptr];
      if (curr_idx >= num_nodes_) {
        std::cerr << "[SpatialIndex] ERROR: node index " << curr_idx << " out of bounds\n";
        continue;
      }

      const auto &node = nodes_[curr_idx];

      float dx = std::max({0.0f, node.min_x - px, px - node.max_x});
      float dy = std::max({0.0f, node.min_y - py, py - node.max_y});
      float bbox_dist_sq = dx * dx + dy * dy;

      if (bbox_dist_sq >= min_dist_sq)
        continue;

      if (node.node_id != traffic::INVALID_NODE) {
        // Leaf Node
        if (!geom_store_) {
          continue;
        }
        auto geom = geom_store_->get_geometry(node.node_id);
        if (geom.size() < 2 || geom.size() > 1000000) {
          continue;
        }

        float edge_total_len = 0.0f;
        float best_seg_dist_sq = std::numeric_limits<float>::max();
        float best_seg_offset_m = 0.0f;

        for (size_t i = 0; i < geom.size() - 1; ++i) {
          float ax = geom[i].x, ay = geom[i].y;
          float bx = geom[i + 1].x, by = geom[i + 1].y;

          auto [dist_sq, t] = ProjectPointOnSegment(px, py, ax, ay, bx, by);

          float seg_dx = bx - ax;
          float seg_dy = by - ay;
          float seg_len = std::sqrt(seg_dx * seg_dx + seg_dy * seg_dy);

          if (dist_sq < best_seg_dist_sq) {
            best_seg_dist_sq = dist_sq;
            best_seg_offset_m = edge_total_len + (t * seg_len);
          }
          edge_total_len += seg_len;
        }

        if (best_seg_dist_sq < min_dist_sq) {
          min_dist_sq = best_seg_dist_sq;
          best_node_id = node.node_id;
          best_offset = (edge_total_len > 0.001f)
                            ? (best_seg_offset_m / edge_total_len)
                            : 0.0f;
        }
      } else {
        // Внутренний узел: добавляем дочерние элементы в стек с эвристикой Branch-and-Bound
        if (stack_ptr + 2 >= MAX_STACK_SIZE) {
          std::cerr << "[SpatialIndex] WARN: R-Tree stack overflow! Skipping branch.\n";
          continue; 
        }

        auto get_bbox_dist_sq = [px, py](const FlatBVHNode& n) {
          float dx = std::max({0.0f, n.min_x - px, px - n.max_x});
          float dy = std::max({0.0f, n.min_y - py, py - n.max_y});
          return dx * dx + dy * dy;
        };

        float dist_left = (node.left_child != traffic::INVALID_NODE && node.left_child < num_nodes_) ? 
                          get_bbox_dist_sq(nodes_[node.left_child]) : std::numeric_limits<float>::max();
        float dist_right = (node.right_child != traffic::INVALID_NODE && node.right_child < num_nodes_) ? 
                           get_bbox_dist_sq(nodes_[node.right_child]) : std::numeric_limits<float>::max();

        // Кладем в стек сначала более дальнего ребенка, чтобы ближний оказался на вершине стека
        if (dist_left < dist_right) {
          if (dist_right < min_dist_sq && node.right_child != traffic::INVALID_NODE) stack[stack_ptr++] = node.right_child;
          if (dist_left < min_dist_sq && node.left_child != traffic::INVALID_NODE)  stack[stack_ptr++] = node.left_child;
        } else {
          if (dist_left < min_dist_sq && node.left_child != traffic::INVALID_NODE)  stack[stack_ptr++] = node.left_child;
          if (dist_right < min_dist_sq && node.right_child != traffic::INVALID_NODE) stack[stack_ptr++] = node.right_child;
        }
      }
    }


    return {best_node_id, best_offset};
  }

private:
  /**
   * @brief Проекция точки P на отрезок AB.
   * @return Пара {квадрат расстояния до проекции, нормализованное смещение t
   * [0,1]}
   */
  [[nodiscard]] static inline std::pair<float, float>
  ProjectPointOnSegment(float px, float py, float ax, float ay, float bx,
                        float by) noexcept {

    float l2 = (bx - ax) * (bx - ax) + (by - ay) * (by - ay);
    if (l2 == 0.0f)
      return {(px - ax) * (px - ax) + (py - ay) * (py - ay), 0.0f};

    // Находим параметр t проекции точки на прямую, ограниченный отрезком [0,1]
    float t = std::max(
        0.0f,
        std::min(1.0f, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2));

    float proj_x = ax + t * (bx - ax);
    float proj_y = ay + t * (by - ay);

    float dx = px - proj_x;
    float dy = py - proj_y;
    return {dx * dx + dy * dy, t};
  }

  const FlatBVHNode *nodes_ = nullptr;
  traffic::PointCount num_nodes_ = 0;
  const GeometryStore *geom_store_ = nullptr;
};

} // namespace traffic::common
