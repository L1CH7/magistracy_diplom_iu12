#pragma once

#include "common/graph_types.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/control/graph_loader.hpp"
#include "router/control/volume_manager.hpp"
#include "common/mmap_region.hpp"
#include "common/spatial_grid.hpp"
#include <string>
#include <expected>
#include <memory>
#include <cstdint>
#include <vector>

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
        traffic::NodeID start_node_idx, 
        traffic::NodeID target_node_idx, 
        uint32_t start_time = 0
    );

    // Маршрут между двумя точками с учетом смещения (offset) на начальном и конечном ребрах
    std::expected<traffic::RouteResponse, std::string> RouteBetweenTwo(
        traffic::RoutePoint start, 
        traffic::RoutePoint target, 
        uint32_t start_time = 0
    );

    // Маршрут через N точек (waypoints)
    std::expected<traffic::RouteResponse, std::string> RouteMultipoint(
        const std::vector<traffic::RoutePoint>& waypoints, 
        uint32_t start_time = 0
    );

    // Маршрут между двумя координатами
    std::expected<traffic::RouteResponse, std::string> RouteByCoords(
        float src_x, float src_y, 
        float dst_x, float dst_y, 
        uint32_t start_time = 0
    );

    // Маршрут через N координат (waypoints)
    std::expected<traffic::RouteResponse, std::string> RouteMultipointByCoords(
        const std::vector<std::pair<float, float>>& coords, 
        uint32_t start_time = 0
    );

    const traffic::GraphView& get_view() const { return mapped_graph_.view; }

    // Helpers for benchmarking
    // Helpers for benchmarking
    traffic::PointCount num_nodes() const noexcept;
    traffic::EdgeID num_edges() const noexcept { return mapped_graph_.geometry_store ? mapped_graph_.geometry_store->num_edges() : 0; }
    
    // Returns coords of the first point of the given edge
    std::pair<float, float> get_edge_coords(traffic::EdgeID edge_id) const noexcept {
        if (!mapped_graph_.geometry_store) return {0.0f, 0.0f};
        auto geom = mapped_graph_.geometry_store->get_geometry(edge_id);
        if (geom.points.empty()) return {0.0f, 0.0f};
        return {geom.points[0].x, geom.points[0].y};
    }

private:
    // Вычисляет длину ребра в метрах на основе его реальной геометрии
    float CalculateEdgeLength(traffic::EdgeID edge_id) const;
    // Оценивает время проезда по ребру (для вычисления смещений)
    float CalculateEdgeTime(traffic::EdgeID edge_id) const;

    MappedGraph mapped_graph_;
    std::unique_ptr<traffic::common::SpatialGrid> spatial_grid_;
    std::unique_ptr<traffic::router::control::VolumeManager> volume_manager_;
};

} // namespace traffic::router::control
