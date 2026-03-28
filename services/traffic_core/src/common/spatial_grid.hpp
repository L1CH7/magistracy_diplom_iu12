#pragma once

#include "geometry_store.hpp"
#include "graph_types.hpp"
#include "mmap_region.hpp"
#include <iostream>
#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <string>
#include <vector>
#include <immintrin.h>

namespace traffic::common {

class SpatialGrid {
public:
    bool load(const std::string& filepath, const GeometryStore* geom_store) {
        geom_store_ = geom_store;
        try {
            region_ = std::make_unique<MmapRegion>(filepath);
            if (region_->empty()) return false;

            const uint8_t* data = static_cast<const uint8_t*>(region_->data());
            
            // 1. Читаем заголовок
            min_x_ = *reinterpret_cast<const float*>(data);
            min_y_ = *reinterpret_cast<const float*>(data + 4);
            max_x_ = *reinterpret_cast<const float*>(data + 8);
            max_y_ = *reinterpret_cast<const float*>(data + 12);
            cell_size_ = *reinterpret_cast<const float*>(data + 16);
            cols_ = *reinterpret_cast<const uint32_t*>(data + 20);
            rows_ = *reinterpret_cast<const uint32_t*>(data + 24);
            
            uint32_t total_nodes = *reinterpret_cast<const uint32_t*>(data + 28);

            // 2. Офсеты указывают на количество узлов (кратно 8)
            size_t header_size = 32;
            cell_offsets_ = reinterpret_cast<const uint32_t*>(data + header_size);
            
            // 3. Данные в формате SoA (блоки по 8 элементов)
            // Поиск начала данных с учетом выравнивания на 32 байта
            size_t offsets_bytes = (rows_ * cols_ + 1) * sizeof(uint32_t);
            size_t raw_soa_start = header_size + offsets_bytes;
            size_t alignment_needed = (32 - (raw_soa_start % 32)) % 32;
            
            soa_data_ = reinterpret_cast<const float*>(data + raw_soa_start + alignment_needed);

            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] traffic::RoutePoint MapToEdge(float px, float py) const noexcept {
        if (!cell_offsets_ || !soa_data_ || !geom_store_) return {traffic::INVALID_NODE, 0.0f};

        // 1. Grid Hashing
        if (px < min_x_ || px > max_x_ || py < min_y_ || py > max_y_) {
            return {traffic::INVALID_NODE, 0.0f};
        }

        uint32_t col = static_cast<uint32_t>((px - min_x_) / cell_size_);
        uint32_t row = static_cast<uint32_t>((py - min_y_) / cell_size_);
        
        if (col >= cols_) col = cols_ - 1;
        if (row >= rows_) row = rows_ - 1;

        uint32_t c_start = (col > 0) ? col - 1 : 0;
        uint32_t c_end = (col < cols_ - 1) ? col + 1 : cols_ - 1;
        uint32_t r_start = (row > 0) ? row - 1 : 0;
        uint32_t r_end = (row < rows_ - 1) ? row + 1 : rows_ - 1;

        float min_dist_sq = std::numeric_limits<float>::max();
        traffic::EdgeID best_node_id = traffic::INVALID_NODE;
        traffic::SegmentOffset best_offset = 0.0f;

        // SIMD подготовка
        __m256 v_px = _mm256_set1_ps(px);
        __m256 v_py = _mm256_set1_ps(py);
        __m256 v_zero = _mm256_setzero_ps();

        for (uint32_t r = r_start; r <= r_end; ++r) {
            for (uint32_t c = c_start; c <= c_end; ++c) {
                uint32_t cell_idx = r * cols_ + c;
                uint32_t start_node_idx = cell_offsets_[cell_idx];
                uint32_t end_node_idx = cell_offsets_[cell_idx + 1];

                // Итерируемся блоками по 8 узлов
                // Каждый блок из 8 узлов занимает 40 float (min_x, min_y, max_x, max_y, ids)
                for (uint32_t i = start_node_idx; i < end_node_idx; i += 8) {
                    const float* block_ptr = soa_data_ + (i / 8) * 40;
                    
                    // Загружаем SoA-компоненты блока
                    __m256 v_min_x = _mm256_load_ps(block_ptr);
                    __m256 v_min_y = _mm256_load_ps(block_ptr + 8);
                    __m256 v_max_x = _mm256_load_ps(block_ptr + 16);
                    __m256 v_max_y = _mm256_load_ps(block_ptr + 24);
                    __m256i v_ids   = _mm256_load_si256(reinterpret_cast<const __m256i*>(block_ptr + 32));

                    // Расчет расстояния до AABB (BBox) для 8 дорог параллельно
                    __m256 dx = _mm256_max_ps(v_zero, _mm256_sub_ps(v_min_x, v_px));
                    dx = _mm256_max_ps(dx, _mm256_sub_ps(v_px, v_max_x));
                    __m256 dy = _mm256_max_ps(v_zero, _mm256_sub_ps(v_min_y, v_py));
                    dy = _mm256_max_ps(dy, _mm256_sub_ps(v_py, v_max_y));
                    
                    __m256 v_bbox_dist_sq = _mm256_add_ps(_mm256_mul_ps(dx, dx), _mm256_mul_ps(dy, dy));
                    
                    // Фильтр по текущему min_dist_sq
                    __m256 v_current_best = _mm256_set1_ps(min_dist_sq);
                    __m256 v_mask = _mm256_cmp_ps(v_bbox_dist_sq, v_current_best, _CMP_LT_OQ);
                    
                    int mask = _mm256_movemask_ps(v_mask);
                    if (mask == 0) continue; // Все 8 дорог блока гарантированно дальше

                    // Скалярная обработка только выживших кандидатов
                    alignas(32) uint32_t ids[8];
                    _mm256_store_si256(reinterpret_cast<__m256i*>(ids), v_ids);

                    for (int j = 0; j < 8; ++j) {
                        if (mask & (1 << j)) {
                            traffic::EdgeID node_id = ids[j];
                            if (node_id == 0xFFFFFFFF) continue;

                            auto geom = geom_store_->get_geometry(node_id);
                            const size_t pt_count = geom.points.size();
                            if (pt_count < 2) continue;

                            float best_seg_dist_sq = std::numeric_limits<float>::max();
                            size_t best_i = 0;
                            float best_t = 0.0f;
                            const Point2D* pts = geom.points.data();

                            for (size_t pt = 0; pt < pt_count - 1; ++pt) {
                                float ax = pts[pt].x, ay = pts[pt].y;
                                float bx = pts[pt+1].x, by = pts[pt+1].y;
                                float dx_seg = bx - ax, dy_seg = by - ay;
                                float l2 = dx_seg * dx_seg + dy_seg * dy_seg + 1e-9f; 
                                float dot = (px - ax) * dx_seg + (py - ay) * dy_seg;
                                float t = std::fmin(1.0f, std::fmax(0.0f, dot / l2));
                                float proj_x = ax + t * dx_seg, proj_y = ay + t * dy_seg;
                                float dist_sq = (px - proj_x)*(px - proj_x) + (py - proj_y)*(py - proj_y);

                                bool is_closer = dist_sq < best_seg_dist_sq;
                                best_seg_dist_sq = is_closer ? dist_sq : best_seg_dist_sq;
                                best_i = is_closer ? pt : best_i;
                                best_t = is_closer ? t : best_t;
                            }

                            if (best_seg_dist_sq < min_dist_sq) {
                                min_dist_sq = best_seg_dist_sq;
                                best_node_id = node_id;
                                float edge_total_len = geom.accum_lens[pt_count - 1];
                                float seg_len = geom.accum_lens[best_i + 1] - geom.accum_lens[best_i];
                                float best_seg_offset_m = geom.accum_lens[best_i] + (best_t * seg_len);
                                best_offset = (edge_total_len > 0.001f) ? (best_seg_offset_m / edge_total_len) : 0.0f;
                            }
                        }
                    }
                }
            }
        }

        return {best_node_id, best_offset};
    }

private:
    std::unique_ptr<MmapRegion> region_;
    const GeometryStore* geom_store_ = nullptr;
    
    float min_x_ = 0, min_y_ = 0, max_x_ = 0, max_y_ = 0, cell_size_ = 0;
    uint32_t cols_ = 0, rows_ = 0;
    
    const uint32_t* cell_offsets_ = nullptr;
    const float* soa_data_ = nullptr;
};

} // namespace traffic::common
