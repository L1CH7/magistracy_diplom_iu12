#pragma once

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
#include <xmmintrin.h>
#include <pmmintrin.h>

namespace traffic::common {

class GeometryStore; // Forward declaration (not needed in hot path anymore)

class SpatialGrid {
public:
    bool load(const std::string& filepath, const GeometryStore* /* unused */ = nullptr) {
        try {
            region_ = std::make_unique<MmapRegion>(filepath);
            if (region_->empty()) return false;

            const uint8_t* data = static_cast<const uint8_t*>(region_->data());
            
            // 1. Читаем заголовок (32 байта)
            min_x_ = *reinterpret_cast<const float*>(data);
            min_y_ = *reinterpret_cast<const float*>(data + 4);
            max_x_ = *reinterpret_cast<const float*>(data + 8);
            max_y_ = *reinterpret_cast<const float*>(data + 12);
            cell_size_ = *reinterpret_cast<const float*>(data + 16);
            cols_ = *reinterpret_cast<const uint32_t*>(data + 20);
            rows_ = *reinterpret_cast<const uint32_t*>(data + 24);
            
            // uint32_t total_segments = *reinterpret_cast<const uint32_t*>(data + 28);

            // 2. Офсеты
            size_t header_size = 32;
            cell_offsets_ = reinterpret_cast<const uint32_t*>(data + header_size);
            
            // 3. Данные в формате SoA (блоки по 8 отрезков, ширина 56 float)
            size_t offsets_bytes = (rows_ * cols_ + 1) * sizeof(uint32_t);
            size_t raw_soa_start = header_size + offsets_bytes;
            size_t alignment_needed = (32 - (raw_soa_start % 32)) % 32;
            
            soa_data_ = reinterpret_cast<const float*>(data + raw_soa_start + alignment_needed);

            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] traffic::RoutePoint MapToEdge(float px, float py) const noexcept {
        if (!cell_offsets_ || !soa_data_) return {traffic::INVALID_NODE, 0.0f};

        _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_ON);
        _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_ON);

        if (px < min_x_ || px > max_x_ || py < min_y_ || py > max_y_) {
            return {traffic::INVALID_NODE, 0.0f};
        }

        uint32_t col = static_cast<uint32_t>((px - min_x_) / cell_size_);
        uint32_t row = static_cast<uint32_t>((py - min_y_) / cell_size_);
        
        if (col >= cols_) col = cols_ - 1;
        if (row >= rows_) row = rows_ - 1;

        float min_dist_sq = std::numeric_limits<float>::max();
        traffic::EdgeID best_node_id = traffic::INVALID_NODE;
        traffic::SegmentOffset best_offset = 0.0f;

        // Spiral Early Exit
        ScanCell(row * cols_ + col, px, py, min_dist_sq, best_node_id, best_offset);

        constexpr float EARLY_EXIT_FACTOR = 0.4f * 0.4f;
        if (best_node_id == traffic::INVALID_NODE || min_dist_sq >= (cell_size_ * cell_size_ * EARLY_EXIT_FACTOR)) {
            constexpr uint32_t RADIUS = 3; // Кольца от 1 до 3 (до 300+ метров)
            for (uint32_t cur_r = 1; cur_r <= RADIUS; ++cur_r) {
                uint32_t c_start = (col >= cur_r) ? col - cur_r : 0;
                uint32_t c_end = (col + cur_r < cols_) ? col + cur_r : cols_ - 1;
                uint32_t r_start = (row >= cur_r) ? row - cur_r : 0;
                uint32_t r_end = (row + cur_r < rows_) ? row + cur_r : rows_ - 1;

                for (uint32_t r = r_start; r <= r_end; ++r) {
                    for (uint32_t c = c_start; c <= c_end; ++c) {
                        // Сканируем только периметр (границы) текущего кольца
                        if (std::abs(static_cast<int>(r) - static_cast<int>(row)) == static_cast<int>(cur_r) || 
                            std::abs(static_cast<int>(c) - static_cast<int>(col)) == static_cast<int>(cur_r)) {
                            ScanCell(r * cols_ + c, px, py, min_dist_sq, best_node_id, best_offset);
                        }
                    }
                }
                // Ранний выход: если на текущем кольце нашли кандидата, дальше не ищем
                if (best_node_id != traffic::INVALID_NODE) {
                    break;
                }
            }
        }

        return {best_node_id, best_offset};
    }

private:
    void ScanCell(uint32_t cell_idx, float px, float py, 
                  float& min_dist_sq, traffic::EdgeID& best_node_id, traffic::SegmentOffset& best_offset) const noexcept {
        uint32_t start_idx = cell_offsets_[cell_idx];
        uint32_t end_idx = cell_offsets_[cell_idx + 1];

        __m256 v_px = _mm256_set1_ps(px);
        __m256 v_py = _mm256_set1_ps(py);
        __m256 v_zero = _mm256_setzero_ps();
        __m256 v_one  = _mm256_set1_ps(1.0f);
        __m256 v_tiny = _mm256_set1_ps(1e-9f);

        // Считаем косинус широты один раз для корректировки гео-пропорций
        float cos_lat = std::cos(py * 3.14159265f / 180.0f);
        __m256 v_cos_lat = _mm256_set1_ps(cos_lat);

        for (uint32_t i = start_idx; i < end_idx; i += 8) {
            const float* block_ptr = soa_data_ + (i / 8) * 56;
            
            __m256 v_ax = _mm256_load_ps(block_ptr);
            __m256 v_ay = _mm256_load_ps(block_ptr + 8);
            __m256 v_bx = _mm256_load_ps(block_ptr + 16);
            __m256 v_by = _mm256_load_ps(block_ptr + 24);
            __m256i v_ids = _mm256_load_si256(reinterpret_cast<const __m256i*>(block_ptr + 32));

            // Проекция X с учетом сужения долготы
            __m256 v_dx_seg = _mm256_mul_ps(_mm256_sub_ps(v_bx, v_ax), v_cos_lat);
            __m256 v_dy_seg = _mm256_sub_ps(v_by, v_ay);
            __m256 v_l2 = _mm256_add_ps(_mm256_mul_ps(v_dx_seg, v_dx_seg), _mm256_mul_ps(v_dy_seg, v_dy_seg));
            
            __m256 v_dx_p = _mm256_mul_ps(_mm256_sub_ps(v_px, v_ax), v_cos_lat);
            __m256 v_dy_p = _mm256_sub_ps(v_py, v_ay);
            __m256 v_dot = _mm256_add_ps(_mm256_mul_ps(v_dx_p, v_dx_seg), _mm256_mul_ps(v_dy_p, v_dy_seg));
            
            __m256 v_l2_tiny = _mm256_add_ps(v_l2, v_tiny);
            __m256 v_inv_l2 = _mm256_rcp_ps(v_l2_tiny); 
            __m256 v_t = _mm256_mul_ps(v_dot, v_inv_l2);
            v_t = _mm256_max_ps(v_zero, _mm256_min_ps(v_one, v_t));
            
            __m256 v_proj_x = _mm256_add_ps(_mm256_mul_ps(v_ax, v_cos_lat), _mm256_mul_ps(v_t, v_dx_seg));
            __m256 v_proj_y = _mm256_add_ps(v_ay, _mm256_mul_ps(v_t, v_dy_seg));
            
            __m256 v_px_scaled = _mm256_mul_ps(v_px, v_cos_lat);
            __m256 v_dist_dx = _mm256_sub_ps(v_px_scaled, v_proj_x);
            __m256 v_dist_dy = _mm256_sub_ps(v_py, v_proj_y);
            __m256 v_d2 = _mm256_add_ps(_mm256_mul_ps(v_dist_dx, v_dist_dx), _mm256_mul_ps(v_dist_dy, v_dist_dy));

            __m256 v_limit = _mm256_set1_ps(min_dist_sq);
            __m256 v_mask = _mm256_cmp_ps(v_d2, v_limit, _CMP_LT_OQ);
            int mask = _mm256_movemask_ps(v_mask);
            
            if (mask == 0) continue;

            alignas(32) float d2s[8];
            _mm256_store_ps(d2s, v_d2);
            alignas(32) uint32_t ids[8];
            _mm256_store_si256(reinterpret_cast<__m256i*>(ids), v_ids);

            bool found_new_min = false;
            int best_j = -1;

            for (int j = 0; j < 8; ++j) {
                if ((mask & (1 << j)) && d2s[j] < min_dist_sq && ids[j] != 0xFFFFFFFF) {
                    min_dist_sq = d2s[j];
                    best_node_id = ids[j];
                    best_j = j;
                    found_new_min = true;
                }
            }

            // ЛЕНИВАЯ ВЫГРУЗКА: Только если нашли реальный минимум!
            if (found_new_min) {
                alignas(32) float ts[8];
                _mm256_store_ps(ts, v_t);
                alignas(32) float l2s[8];
                _mm256_store_ps(l2s, v_l2);
                
                // Загружаем base_offs и totals только из нужной ячейки (избегаем выгрузки всего регистра)
                float best_base_off = *(block_ptr + 40 + best_j);
                float best_total_len = *(block_ptr + 48 + best_j);
                
                float current_meters = best_base_off + (ts[best_j] * std::sqrt(l2s[best_j]) * 111139.0f);
                best_offset = (best_total_len > 0.001f) ? (current_meters / best_total_len) : 0.0f;
            }
        }
    }

    std::unique_ptr<MmapRegion> region_;
    float min_x_ = 0, min_y_ = 0, max_x_ = 0, max_y_ = 0, cell_size_ = 0;
    uint32_t cols_ = 0, rows_ = 0;
    const uint32_t* cell_offsets_ = nullptr;
    const float* soa_data_ = nullptr;
};

} // namespace traffic::common
