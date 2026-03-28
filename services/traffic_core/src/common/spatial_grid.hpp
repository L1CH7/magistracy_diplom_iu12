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

            // 2. Указатели на плоские массивы
            size_t header_size = 32;
            cell_offsets_ = reinterpret_cast<const uint32_t*>(data + header_size);
            cell_nodes_ = reinterpret_cast<const uint32_t*>(data + header_size + (rows_ * cols_ + 1) * sizeof(uint32_t));

            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] traffic::RoutePoint MapToEdge(float px, float py) const noexcept {
        if (!cell_offsets_ || !cell_nodes_ || !geom_store_) return {traffic::INVALID_NODE, 0.0f};

        // 1. O(1) Grid Hashing
        if (px < min_x_ || px > max_x_ || py < min_y_ || py > max_y_) {
            return {traffic::INVALID_NODE, 0.0f};
        }

        uint32_t col = static_cast<uint32_t>((px - min_x_) / cell_size_);
        uint32_t row = static_cast<uint32_t>((py - min_y_) / cell_size_);
        
        // Защита от выхода за границы из-за float precision
        if (col >= cols_) col = cols_ - 1;
        if (row >= rows_) row = rows_ - 1;

        // Поиск в 9 соседних ячейках (3x3), чтобы избежать краевых эффектов (если точка на границе ячейки)
        uint32_t c_start = (col > 0) ? col - 1 : 0;
        uint32_t c_end = (col < cols_ - 1) ? col + 1 : cols_ - 1;
        uint32_t r_start = (row > 0) ? row - 1 : 0;
        uint32_t r_end = (row < rows_ - 1) ? row + 1 : rows_ - 1;

        float min_dist_sq = std::numeric_limits<float>::max();
        traffic::EdgeID best_node_id = traffic::INVALID_NODE;
        traffic::SegmentOffset best_offset = 0.0f;

        // Проверяем локальные ячейки
        for (uint32_t r = r_start; r <= r_end; ++r) {
            for (uint32_t c = c_start; c <= c_end; ++c) {
                uint32_t cell_idx = r * cols_ + c;
                uint32_t start_idx = cell_offsets_[cell_idx];
                uint32_t end_idx = cell_offsets_[cell_idx + 1];

                // Linear Scan по кандидатам из L1-кэша
                for (uint32_t i = start_idx; i < end_idx; ++i) {
                    traffic::EdgeID node_id = cell_nodes_[i];
                    auto geom = geom_store_->get_geometry(node_id);
                    const size_t pt_count = geom.points.size();
                    if (pt_count < 2) continue;

                    float best_seg_dist_sq = std::numeric_limits<float>::max();
                    size_t best_i = 0;
                    float best_t = 0.0f;
                    const Point2D* pts = geom.points.data();

                    // Branchless Math Loop
                    #pragma GCC ivdep
                    for (size_t pt = 0; pt < pt_count - 1; ++pt) {
                        float ax = pts[pt].x, ay = pts[pt].y;
                        float bx = pts[pt+1].x, by = pts[pt+1].y;

                        float dx_seg = bx - ax;
                        float dy_seg = by - ay;
                        float l2 = dx_seg * dx_seg + dy_seg * dy_seg + 1e-9f; 
                        float dot = (px - ax) * dx_seg + (py - ay) * dy_seg;
                        
                        float t = std::fmin(1.0f, std::fmax(0.0f, dot / l2));

                        float proj_x = ax + t * dx_seg;
                        float proj_y = ay + t * dy_seg;

                        float dx = px - proj_x;
                        float dy = py - proj_y;
                        float dist_sq = dx * dx + dy * dy;

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

        return {best_node_id, best_offset};
    }

private:
    std::unique_ptr<MmapRegion> region_;
    const GeometryStore* geom_store_ = nullptr;
    
    float min_x_ = 0, min_y_ = 0, max_x_ = 0, max_y_ = 0, cell_size_ = 0;
    uint32_t cols_ = 0, rows_ = 0;
    
    const uint32_t* cell_offsets_ = nullptr;
    const uint32_t* cell_nodes_ = nullptr;
};

} // namespace traffic::common
