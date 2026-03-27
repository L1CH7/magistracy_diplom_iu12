#pragma once

#include "common/graph_types.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/control/graph_loader.hpp"
#include "common/mmap_region.hpp"
#include <string>
#include <expected>
#include <memory>
#include <cstdint>

namespace traffic::router::control {

class RouterManager {
public:
    RouterManager();
    ~RouterManager();

    // Disable copy/move for safety with refs
    RouterManager(const RouterManager&) = delete;
    RouterManager& operator=(const RouterManager&) = delete;

    std::expected<void, std::string> LoadGraphs(const std::string& data_dir);
    
    std::expected<traffic::RoutingResult, std::string> Route(
        uint32_t start_node_idx, 
        uint32_t target_node_idx, 
        uint32_t start_time = 0
    );

    const traffic::GraphView& get_view() const { return mapped_graph_.view; }

private:
    MappedGraph mapped_graph_;
    std::unique_ptr<router::TdAltRouter> router_;
};

} // namespace traffic::router::control
