#pragma once

#include "geometry_store.hpp"
#include "graph_types.hpp"
#include <algorithm>
#include <cmath>
#include <immintrin.h>
#include <iostream>
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
  [[nodiscard]] traffic::RoutePoint MapToEdge(float px,
                                              float py) const noexcept {
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
        std::cerr << "[SpatialIndex] ERROR: node index " << curr_idx
                  << " out of bounds\n";
        continue;
      }

      const auto &node = nodes_[curr_idx];

      float dx_node = std::max({0.0f, node.min_x - px, px - node.max_x});
      float dy_node = std::max({0.0f, node.min_y - py, py - node.max_y});
      float bbox_dist_sq = dx_node * dx_node + dy_node * dy_node;

      if (bbox_dist_sq >= min_dist_sq)
        continue;

      if (node.node_id != traffic::INVALID_NODE) {
        if (!geom_store_)
          continue;
        auto geom = geom_store_->get_geometry(node.node_id);
        const size_t pt_count = geom.points.size();
        if (pt_count < 2 || pt_count > 1000000)
          continue;
        float best_seg_dist_sq = std::numeric_limits<float>::max();
        size_t best_i = 0;
        float best_t = 0.0f;
        const Point2D *pts = geom.points.data();
        size_t i = 0;

#if defined(__AVX2__)
        __m256 v_px = _mm256_set1_ps(px);
        __m256 v_py = _mm256_set1_ps(py);
        __m256 v_min_dist = _mm256_set1_ps(std::numeric_limits<float>::max());
        __m256 v_best_t = _mm256_setzero_ps();
        __m256i v_best_idx = _mm256_setzero_si256();

        __m256i v_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
        __m256 v_eps = _mm256_set1_ps(1e-9f);
        __m256 v_zero = _mm256_setzero_ps();
        __m256 v_one = _mm256_set1_ps(1.0f);

        // AVX2 HOT LOOP: 8 segments per instruction
        for (; i + 8 < pt_count; i += 8) {
          // Gather SoA vectors from AoS memory (Scale=8 bytes per Point2D)
          __m256 v_ax =
              _mm256_i32gather_ps((const float *)(pts + i), v_offsets, 8);
          __m256 v_ay =
              _mm256_i32gather_ps(((const float *)(pts + i)) + 1, v_offsets, 8);

          __m256 v_bx =
              _mm256_i32gather_ps((const float *)(pts + i + 1), v_offsets, 8);
          __m256 v_by = _mm256_i32gather_ps(((const float *)(pts + i + 1)) + 1,
                                            v_offsets, 8);

          __m256 v_dx_seg = _mm256_sub_ps(v_bx, v_ax);
          __m256 v_dy_seg = _mm256_sub_ps(v_by, v_ay);

          // l2 = dx^2 + dy^2 + eps
          __m256 v_l2 =
              _mm256_add_ps(_mm256_add_ps(_mm256_mul_ps(v_dx_seg, v_dx_seg),
                                          _mm256_mul_ps(v_dy_seg, v_dy_seg)),
                            v_eps);

          // dot = dp_x*dx_seg + dp_y*dy_seg
          __m256 v_dx_p = _mm256_sub_ps(v_px, v_ax);
          __m256 v_dy_p = _mm256_sub_ps(v_py, v_ay);
          __m256 v_dot = _mm256_add_ps(_mm256_mul_ps(v_dx_p, v_dx_seg),
                                       _mm256_mul_ps(v_dy_p, v_dy_seg));

          // t = clamp(dot / l2, 0.0, 1.0)
          __m256 v_t = _mm256_max_ps(
              v_zero, _mm256_min_ps(v_one, _mm256_div_ps(v_dot, v_l2)));

          // proj = a + t * d_seg
          __m256 v_proj_x = _mm256_add_ps(v_ax, _mm256_mul_ps(v_t, v_dx_seg));
          __m256 v_proj_y = _mm256_add_ps(v_ay, _mm256_mul_ps(v_t, v_dy_seg));

          // dist_sq = (px - proj_x)^2 + (py - proj_y)^2
          __m256 v_dist_dx = _mm256_sub_ps(v_px, v_proj_x);
          __m256 v_dist_dy = _mm256_sub_ps(v_py, v_proj_y);
          __m256 v_dist_sq = _mm256_add_ps(_mm256_mul_ps(v_dist_dx, v_dist_dx),
                                           _mm256_mul_ps(v_dist_dy, v_dist_dy));

          // Update Local Min (Blend based on comparison)
          __m256 mask = _mm256_cmp_ps(v_dist_sq, v_min_dist, _CMP_LT_OQ);
          v_min_dist = _mm256_blendv_ps(v_min_dist, v_dist_sq, mask);
          v_best_t = _mm256_blendv_ps(v_best_t, v_t, mask);

          __m256i v_curr_idx = _mm256_add_epi32(
              _mm256_set1_epi32(static_cast<int>(i)), v_offsets);
          v_best_idx = _mm256_castps_si256(
              _mm256_blendv_ps(_mm256_castsi256_ps(v_best_idx),
                               _mm256_castsi256_ps(v_curr_idx), mask));
        }

        // Horizontal reduction of AVX2 vectors
        alignas(32) float dist_arr[8];
        alignas(32) uint32_t idx_arr[8];
        alignas(32) float t_arr[8];
        _mm256_store_ps(dist_arr, v_min_dist);
        _mm256_store_si256((__m256i *)idx_arr, v_best_idx);
        _mm256_store_ps(t_arr, v_best_t);

        for (int j = 0; j < 8; ++j) {
          if (dist_arr[j] < best_seg_dist_sq) {
            best_seg_dist_sq = dist_arr[j];
            best_i = idx_arr[j];
            best_t = t_arr[j];
          }
        }
#endif

        // Scalar Tail Loop (Handles remaining points < 8)
        for (; i < pt_count - 1; ++i) {
          float ax = pts[i].x, ay = pts[i].y;
          float bx = pts[i + 1].x, by = pts[i + 1].y;

          float dx_seg = bx - ax;
          float dy_seg = by - ay;

          // Epsilon для исключения ветвления на деление на ноль
          float l2 = dx_seg * dx_seg + dy_seg * dy_seg + 1e-9f;
          float dot = (px - ax) * dx_seg + (py - ay) * dy_seg;

          // fminf/fmaxf жестко маппятся в аппаратные инструкции без ветвлений
          float t = fminf(1.0f, fmaxf(0.0f, dot / l2));

          float proj_x = ax + t * dx_seg;
          float proj_y = ay + t * dy_seg;

          float dx = px - proj_x;
          float dy = py - proj_y;
          float dist_sq = dx * dx + dy * dy;

          // Явный паттерн для генерации инструкции CMOV (Conditional Move)
          bool is_closer = dist_sq < best_seg_dist_sq;
          best_seg_dist_sq = is_closer ? dist_sq : best_seg_dist_sq;
          best_i = is_closer ? i : best_i;
          best_t = is_closer ? t : best_t;
        }

        if (best_seg_dist_sq < min_dist_sq) {
          min_dist_sq = best_seg_dist_sq;
          best_node_id = node.node_id;

          float edge_total_len = geom.accum_lens[pt_count - 1];
          float seg_len = geom.accum_lens[best_i + 1] - geom.accum_lens[best_i];
          float best_seg_offset_m =
              geom.accum_lens[best_i] + (best_t * seg_len);

          best_offset = (edge_total_len > 0.001f)
                            ? (best_seg_offset_m / edge_total_len)
                            : 0.0f;
        }
      } else {
        // Внутренний узел: добавляем дочерние элементы в стек с эвристикой
        // Branch-and-Bound
        if (stack_ptr + 2 >= MAX_STACK_SIZE) {
          std::cerr << "[SpatialIndex] WARN: R-Tree stack overflow! Skipping "
                       "branch.\n";
          continue;
        }

        auto get_bbox_dist_sq = [px, py](const FlatBVHNode &n) {
          float dx = std::max({0.0f, n.min_x - px, px - n.max_x});
          float dy = std::max({0.0f, n.min_y - py, py - n.max_y});
          return dx * dx + dy * dy;
        };

        float dist_left = (node.left_child != traffic::INVALID_NODE &&
                           node.left_child < num_nodes_)
                              ? get_bbox_dist_sq(nodes_[node.left_child])
                              : std::numeric_limits<float>::max();
        float dist_right = (node.right_child != traffic::INVALID_NODE &&
                            node.right_child < num_nodes_)
                               ? get_bbox_dist_sq(nodes_[node.right_child])
                               : std::numeric_limits<float>::max();

        if (dist_left < dist_right) {
          if (dist_right < min_dist_sq &&
              node.right_child != traffic::INVALID_NODE)
            stack[stack_ptr++] = node.right_child;
          if (dist_left < min_dist_sq &&
              node.left_child != traffic::INVALID_NODE)
            stack[stack_ptr++] = node.left_child;
        } else {
          if (dist_left < min_dist_sq &&
              node.left_child != traffic::INVALID_NODE)
            stack[stack_ptr++] = node.left_child;
          if (dist_right < min_dist_sq &&
              node.right_child != traffic::INVALID_NODE)
            stack[stack_ptr++] = node.right_child;
        }
      }
    }

    return {best_node_id, best_offset};
  }

private:
  const FlatBVHNode *nodes_ = nullptr;
  traffic::PointCount num_nodes_ = 0;
  const GeometryStore *geom_store_ = nullptr;
};

} // namespace traffic::common
