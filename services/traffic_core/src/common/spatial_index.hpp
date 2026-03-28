#pragma once

#include "geometry_store.hpp"
#include "graph_types.hpp"
#include "logger.hpp"
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
  SpatialIndex(const FlatBVHNode *nodes, uint32_t num_nodes,
               const GeometryStore *geom_store)
      : nodes_(nodes), num_nodes_(num_nodes), geom_store_(geom_store) {}

  /**
   * @brief Находит ближайшее ребро и точку проекции на нем.
   * @param px Долгота (X)
   * @param py Широта (Y)
   * @return RoutePoint с ID ребра и смещением (0.0 - 1.0)
   */
  [[nodiscard]] RoutePoint MapToEdge(float px, float py) const noexcept {
    LOG_DEBUG("MapToEdge: query point ({}, {})", px, py);
    if (num_nodes_ == 0 || !nodes_) {
      LOG_ERROR("MapToEdge: index is empty or null!");
      return {traffic::INVALID_NODE, 0.0f};
    }

    float min_dist_sq = std::numeric_limits<float>::max();
    traffic::NodeID best_node_id = traffic::INVALID_NODE;
    float best_offset = 0.0f;

    // Стек для обхода дерева (фиксированный размер)
    static constexpr size_t MAX_STACK_SIZE = 128;
    uint32_t stack[MAX_STACK_SIZE];
    uint32_t stack_ptr = 0;
    stack[stack_ptr++] = 0;

    while (stack_ptr > 0) {
      uint32_t curr_idx = stack[--stack_ptr];
      if (curr_idx >= num_nodes_) {
        LOG_ERROR("SpatialIndex: node index {} out of bounds (max {})",
                  curr_idx, num_nodes_);
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
          LOG_ERROR("SpatialIndex: GeometryStore is null!");
          continue;
        }
        auto geom = geom_store_->get_geometry(node.node_id);
        if (geom.size() < 2 || geom.size() > 1000000) {
          if (geom.size() > 1000000) {
            LOG_ERROR("SpatialIndex: Detected corrupt geometry size {} for node {}", geom.size(), node.node_id);
          }
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
        // Internal Node
        if (stack_ptr + 2 >= MAX_STACK_SIZE) {
          LOG_WARN("SpatialIndex: stack full (ptr={}, max={})", stack_ptr,
                   MAX_STACK_SIZE);
          continue;
        }

        if (node.left_child != traffic::INVALID_NODE) {
          if (node.left_child < num_nodes_)
            stack[stack_ptr++] = node.left_child;
          else
            LOG_ERROR("SpatialIndex: left_child {} out of bounds",
                      node.left_child);
        }
        if (node.right_child != traffic::INVALID_NODE) {
          if (node.right_child < num_nodes_)
            stack[stack_ptr++] = node.right_child;
          else
            LOG_ERROR("SpatialIndex: right_child {} out of bounds",
                      node.right_child);
        }
      }
    }

    if (best_node_id != traffic::INVALID_NODE) {
      LOG_DEBUG("MapToEdge SUCCESS: point ({}, {}) -> edge {}, offset {:.3f}",
                px, py, best_node_id, best_offset);
    } else {
      LOG_WARN("MapToEdge FAILED for point ({}, {})", px, py);
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
  uint32_t num_nodes_ = 0;
  const GeometryStore *geom_store_ = nullptr;
};

} // namespace traffic::common
