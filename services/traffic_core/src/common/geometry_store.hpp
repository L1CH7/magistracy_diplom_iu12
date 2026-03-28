#pragma once
#include "graph_types.hpp"
#include "mmap_region.hpp"
#include <memory>
#include <span>
#include <string>
#include <cstdint>

namespace traffic::common {

struct Point2D { float x, y; };

/**
 * @brief GeometryStore Provides mmap-based access to edge geometry (polyline points).
 */
class GeometryStore {
public:
    bool load(const std::string& filepath) {
        try {
            region_ = std::make_unique<MmapRegion>(filepath);
            if (region_->empty()) return false;
            
            size_t size = region_->size();
            const uint8_t* data = static_cast<const uint8_t*>(region_->data());
            
            if (size < sizeof(traffic::EdgeID) * 2) return false;
            num_edges_ = *reinterpret_cast<const traffic::EdgeID*>(data);
            traffic::PointCount total_points = *reinterpret_cast<const traffic::PointCount*>(data + sizeof(traffic::EdgeID));
            
            size_t min_offsets_size = sizeof(traffic::EdgeID) * 2 + (num_edges_ + 1) * sizeof(uint32_t);
            if (size < min_offsets_size) return false;

            offsets_ = reinterpret_cast<const uint32_t*>(data + sizeof(traffic::EdgeID) * 2);
            
            traffic::PointCount verified_total_points = offsets_[num_edges_];
            if (verified_total_points != total_points) {
                // Warning: data inconsistent, but we can continue or return error
            }

            size_t total_required_size = min_offsets_size + verified_total_points * sizeof(Point2D);
            if (size < total_required_size) return false;

            points_ = reinterpret_cast<const Point2D*>(data + min_offsets_size);
            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] std::span<const Point2D> get_geometry(traffic::EdgeID edge_id) const noexcept {
        if (!points_ || edge_id >= num_edges_) return {};
        const uint32_t start = offsets_[edge_id];
        const uint32_t end = offsets_[edge_id + 1];
        return {points_ + start, end - start};
    }

    [[nodiscard]] traffic::EdgeID num_edges() const noexcept { return num_edges_; }

private:
    std::unique_ptr<MmapRegion> region_;
    traffic::EdgeID num_edges_ = 0;
    const uint32_t* offsets_ = nullptr;
    const Point2D* points_ = nullptr;
};

} // namespace traffic::common
