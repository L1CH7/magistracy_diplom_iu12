#include "router/control/router_manager.hpp"
#include "common/logger.hpp"
#include <format>
#include <filesystem>
#include <cstring>
#include <cmath>
#include <numbers>

namespace traffic::router::control {

RouterManager::RouterManager() = default;
RouterManager::~RouterManager() = default;
 
traffic::PointCount RouterManager::num_nodes() const noexcept {
    if (!mapped_graph_.csr_region) return 0;
    const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
    traffic::PointCount num_nodes;
    std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));
    return num_nodes;
}

std::expected<void, std::string> RouterManager::LoadGraphs(const std::string& data_dir) {
    if (!mapped_graph_.load(data_dir)) {
        return std::unexpected(std::string("Failed to mmap CSR graph from ") + data_dir);
    }

    const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
    traffic::PointCount num_nodes;
    std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));

    if (mapped_graph_.spatial_grid_region) {
        spatial_grid_ = std::make_unique<traffic::common::SpatialGrid>();
        if (!spatial_grid_->load("/app/data/spatial_grid.bin", mapped_graph_.geometry_store.get())) {
            return std::unexpected("Failed to load spatial_grid.bin");
        }
        LOG_INFO("Spatial grid loaded successfully (O(1) lookup enabled)");
    }

    volume_manager_ = std::make_unique<traffic::router::control::VolumeManager>(num_nodes);

    return {};
}


float RouterManager::CalculateEdgeLength(traffic::EdgeID edge_id) const {
    if (!mapped_graph_.geometry_store) return 0.0f;
    auto geom = mapped_graph_.geometry_store->get_geometry(edge_id);
    if (geom.accum_lens.size() < 2) return 0.0f;
    return geom.accum_lens.back();
}

float RouterManager::CalculateEdgeTime(traffic::EdgeID edge_id) const {
    float len = CalculateEdgeLength(edge_id);
    if (len == 0.0f) return 10.0f; // Фоллбек
    return len / 13.8f; // ~50 км/ч
}


} // namespace traffic::router::control
