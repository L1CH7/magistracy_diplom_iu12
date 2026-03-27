#include "router/control/router_manager.hpp"
#include "common/logger.hpp"
#include <format>
#include <filesystem>
#include <cstring>

namespace traffic::router::control {

RouterManager::RouterManager() = default;
RouterManager::~RouterManager() = default;

std::expected<void, std::string> RouterManager::LoadGraphs(const std::string& data_dir) {
    if (!mapped_graph_.load(data_dir)) {
        return std::unexpected(std::string("Failed to mmap CSR graph from ") + data_dir);
    }

    const uint32_t* header = reinterpret_cast<const uint32_t*>(mapped_graph_.csr_region->data());
    uint32_t num_nodes = header[0];

    router_ = std::make_unique<TdAltRouter>(mapped_graph_.view, num_nodes);

    if (mapped_graph_.landmarks_region) {
        router_->get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()));
    }

    return {};
}

std::expected<traffic::RoutingResult, std::string> RouterManager::Route(
    uint32_t start_node_idx, 
    uint32_t target_node_idx, 
    uint32_t start_time
) {
    if (!router_) return std::unexpected(std::string("Router not initialized"));
    return router_->find_path(start_node_idx, target_node_idx);
}

} // namespace traffic::router::control
