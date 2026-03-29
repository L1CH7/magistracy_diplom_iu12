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

std::expected<void, std::string> RouterManager::LoadGraphs(const std::string& data_dir) {
    if (!mapped_graph_.load(data_dir)) {
        return std::unexpected(std::string("Failed to mmap CSR graph from ") + data_dir);
    }

    const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
    traffic::PointCount num_nodes;
    std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));

    router_ = std::make_unique<TdAltRouter>(mapped_graph_.view, num_nodes);

    if (mapped_graph_.landmarks_region) {
        router_->get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()));
    }

    if (mapped_graph_.spatial_grid_region) {
        spatial_grid_ = std::make_unique<traffic::common::SpatialGrid>();
        if (!spatial_grid_->load("/app/data/spatial_grid.bin", mapped_graph_.geometry_store.get())) {
            return std::unexpected("Failed to load spatial_grid.bin");
        }
        LOG_INFO("Spatial grid loaded successfully (O(1) lookup enabled)");
    }

    return {};
}

std::expected<traffic::RoutingResult, std::string> RouterManager::Route(
    traffic::NodeID start_node_idx, 
    traffic::NodeID target_node_idx, 
    uint32_t start_time
) {
    if (!router_) return std::unexpected(std::string("Router not initialized"));
    
    if (start_node_idx >= router_->num_nodes() || target_node_idx >= router_->num_nodes()) {
        return std::unexpected(std::format("Node index out of range: start={}, target={}, max={}", 
                                          start_node_idx, target_node_idx, router_->num_nodes()));
    }

    return router_->find_path_with_telemetry(start_node_idx, target_node_idx);
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

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteBetweenTwo(
    traffic::RoutePoint start, 
    traffic::RoutePoint target, 
    uint32_t start_time
) {
    if (!router_) return std::unexpected(std::string("Router not initialized"));

    float start_time_full = CalculateEdgeTime(start.edge_id);
    float target_time_full = CalculateEdgeTime(target.edge_id);

    // 1. Случай: Старт и Финиш на одном ребре
    if (start.edge_id == target.edge_id && start.offset <= target.offset) {
        traffic::RouteResponse res;
        res.path = {start.edge_id};
        res.total_time = static_cast<uint32_t>((target.offset - start.offset) * start_time_full);
        res.total_length_m = (target.offset - start.offset) * CalculateEdgeLength(start.edge_id);
        return res;
    }

    // 2. Обычный межреберный маршрут
    auto res = Route(start.edge_id, target.edge_id, start_time);
    if (!res) return std::unexpected(res.error());

    // 3. Корректировка времени (Partial Edges)
    uint32_t start_penalty = static_cast<uint32_t>((1.0f - start.offset) * start_time_full);
    uint32_t target_discount = static_cast<uint32_t>((1.0f - target.offset) * target_time_full);

    traffic::RouteResponse final_res;
    final_res.total_time = res->total_weight + start_penalty - target_discount;
    final_res.total_iterations = res->iterations;
    final_res.path = std::move(res->path);
    
    // Суммируем реальную длину всего пути
    final_res.total_length_m = 0.0f;
    for (size_t i = 0; i < final_res.path.size(); ++i) {
        float edge_len = CalculateEdgeLength(final_res.path[i]);
        if (i == 0) edge_len *= (1.0f - start.offset);
        if (i == final_res.path.size() - 1 && final_res.path.size() > 1) edge_len *= target.offset;
        final_res.total_length_m += edge_len;
    }
    
    return final_res;
}

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteMultipoint(
    const std::vector<traffic::RoutePoint>& waypoints, 
    uint32_t start_time
) {
    if (waypoints.size() < 2) {
        return std::unexpected(std::string("At least 2 waypoints required"));
    }

    traffic::RouteResponse global_res;
    global_res.total_time = 0;
    global_res.total_length_m = 0.0f;
    uint32_t current_time = start_time;

    for (size_t i = 0; i < waypoints.size() - 1; ++i) {
        auto segment_res = RouteBetweenTwo(waypoints[i], waypoints[i+1], current_time);
        if (!segment_res) return segment_res;

        global_res.total_time += segment_res->total_time;
        global_res.total_length_m += segment_res->total_length_m;
        global_res.total_iterations += segment_res->total_iterations;
        current_time += segment_res->total_time;

        // Конкатенация пути с дедупликацией на стыках
        if (global_res.path.empty()) {
            global_res.path = std::move(segment_res->path);
        } else {
            const auto& segment_path = segment_res->path;
            size_t start_idx = 0;
            // Конец предыдущего плеча совпадает с началом следующего
            if (!segment_path.empty() && segment_path.front() == global_res.path.back()) {
                start_idx = 1;
            }
            global_res.path.insert(global_res.path.end(), 
                                 segment_path.begin() + start_idx, 
                                 segment_path.end());
        }
    }

    return global_res;
}

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteByCoords(
    float src_x, float src_y, 
    float dst_x, float dst_y, 
    uint32_t start_time
) {
    if (!spatial_grid_) return std::unexpected(std::string("Spatial grid not loaded"));

    auto start_pt = spatial_grid_->MapToEdge(src_x, src_y);
    auto target_pt = spatial_grid_->MapToEdge(dst_x, dst_y);

    if (start_pt.edge_id == traffic::INVALID_NODE || target_pt.edge_id == traffic::INVALID_NODE) {
        return std::unexpected(std::string("Failed to map coordinates to graph"));
    }

    return RouteBetweenTwo(start_pt, target_pt, start_time);
}

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteMultipointByCoords(
    const std::vector<std::pair<float, float>>& coords, 
    uint32_t start_time
) {
    if (!spatial_grid_) return std::unexpected(std::string("Spatial grid not loaded"));
    if (coords.size() < 2) return std::unexpected(std::string("At least 2 coordinates required"));

    std::vector<traffic::RoutePoint> waypoints;
    waypoints.reserve(coords.size());

    for (const auto& cp : coords) {
        auto wp = spatial_grid_->MapToEdge(cp.first, cp.second);
        if (wp.edge_id == traffic::INVALID_NODE) {
            return std::unexpected(std::format("Failed to map waypoint ({}, {}) to graph", cp.first, cp.second));
        }
        waypoints.push_back(wp);
    }

    return RouteMultipoint(waypoints, start_time);
}

} // namespace traffic::router::control
