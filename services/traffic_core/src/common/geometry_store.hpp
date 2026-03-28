#pragma once
#include "graph_types.hpp"
#include "mmap_region.hpp"
#include <memory>
#include <span>
#include <string>
#include <cstdint>

namespace traffic::common {

struct Point2D { float x, y; };

struct EdgeGeometry {
    std::span<const Point2D> points;
    std::span<const float> accum_lens;
};

/**
 * @brief GeometryStore Provides mmap-based access to edge geometry (polyline points).
 */
class GeometryStore {
public:
    bool load(const std::string& filepath) {
        try {
            region_ = std::make_unique<MmapRegion>(filepath);
            if (region_->empty()) return false;
            
            const uint8_t* data = static_cast<const uint8_t*>(region_->data());
            
            num_edges_ = *reinterpret_cast<const uint32_t*>(data);
            uint32_t total_points = *reinterpret_cast<const uint32_t*>(data + 4);
            offsets_ = reinterpret_cast<const uint32_t*>(data + 8);
            
            size_t current_offset = 8 + (num_edges_ + 1) * sizeof(uint32_t);
            size_t pad1 = (8 - (current_offset % 8)) % 8;
            current_offset += pad1;
            
            points_ = reinterpret_cast<const Point2D*>(data + current_offset);
            
            current_offset += total_points * sizeof(Point2D);
            size_t pad2 = (8 - (current_offset % 8)) % 8;
            current_offset += pad2;
            
            lens_ = reinterpret_cast<const float*>(data + current_offset);

            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] EdgeGeometry get_geometry(traffic::EdgeID edge_id) const noexcept {
        if (!points_ || !lens_ || edge_id >= num_edges_) return {};
        uint32_t start = offsets_[edge_id];
        uint32_t end = offsets_[edge_id + 1];
        uint32_t count = end - start;
        return { {points_ + start, count}, {lens_ + start, count} };
    }

    [[nodiscard]] traffic::EdgeID num_edges() const noexcept { return num_edges_; }

private:
    std::unique_ptr<MmapRegion> region_;
    traffic::EdgeID num_edges_ = 0;
    const uint32_t* offsets_ = nullptr;
    const Point2D* points_ = nullptr;
    const float* lens_ = nullptr;
};

} // namespace traffic::common
