#pragma once
#include "common/graph_types.hpp"
#include "common/mmap_region.hpp"
#include <memory>
#include <span>
#include <string>

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
            
            const uint8_t* data = static_cast<const uint8_t*>(region_->data());
            
            num_edges_ = *reinterpret_cast<const uint32_t*>(data);
            offsets_ = reinterpret_cast<const uint32_t*>(data + sizeof(uint32_t));
            points_ = reinterpret_cast<const Point2D*>(data + sizeof(uint32_t) + (num_edges_ + 1) * sizeof(uint32_t));
            return true;
        } catch (...) { return false; }
    }

    [[nodiscard]] std::span<const Point2D> get_geometry(NodeID edge_id) const noexcept {
        if (!points_ || edge_id >= num_edges_) return {};
        uint32_t start = offsets_[edge_id];
        uint32_t end = offsets_[edge_id + 1];
        return {points_ + start, end - start};
    }

    [[nodiscard]] uint32_t num_edges() const noexcept { return num_edges_; }

private:
    std::unique_ptr<MmapRegion> region_;
    uint32_t num_edges_ = 0;
    const uint32_t* offsets_ = nullptr;
    const Point2D* points_ = nullptr;
};

} // namespace traffic::common
