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

    const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
    traffic::NodeID num_nodes;
    std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));

    router_ = std::make_unique<TdAltRouter>(mapped_graph_.view, num_nodes);

    if (mapped_graph_.landmarks_region) {
        router_->get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()));
    }

    if (mapped_graph_.rtree_region) {
        const uint8_t* rtree_ptr = static_cast<const uint8_t*>(mapped_graph_.rtree_region->data());
        uint32_t rtree_nodes_count;
        std::memcpy(&rtree_nodes_count, rtree_ptr, sizeof(rtree_nodes_count));
        const traffic::FlatBVHNode* rtree_nodes = reinterpret_cast<const traffic::FlatBVHNode*>(rtree_ptr + sizeof(rtree_nodes_count));
        spatial_index_ = std::make_unique<traffic::common::SpatialIndex>(
            rtree_nodes, rtree_nodes_count, mapped_graph_.geometry_store.get());
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

    return router_->find_path(start_node_idx, target_node_idx);
}

static constexpr float DUMMY_EDGE_TIME = 10.0f;

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteBetweenTwo(
    traffic::RoutePoint start, 
    traffic::RoutePoint target, 
    uint32_t start_time
) {
    if (!router_) return std::unexpected(std::string("Router not initialized"));

    // 1. Случай: Старт и Финиш на одном ребре
    if (start.edge_id == target.edge_id && start.offset <= target.offset) {
        traffic::RouteResponse res;
        res.path = {start.edge_id};
        // Заглушка: DUMMY_EDGE_TIME секунд на все ребро. Считаем пропорционально пройденному пути.
        res.total_time = static_cast<uint32_t>((target.offset - start.offset) * DUMMY_EDGE_TIME);
        return res;
    }

    // 2. Обычный межреберный маршрут
    auto res = Route(start.edge_id, target.edge_id, start_time);
    if (!res) return std::unexpected(res.error());

    // 3. Корректировка времени (Partial Edges)
    // TdAltRouter считает полное время всех ребер в path.
    // Нам нужно: прибавить время от старта до конца первого ребра, 
    // и вычесть время, которое мы НЕ проедем в конце целевого ребра.
    // Пока используем константу DUMMY_EDGE_TIME как время проезда целого ребра.
    uint32_t start_penalty = static_cast<uint32_t>((1.0f - start.offset) * DUMMY_EDGE_TIME);
    uint32_t target_discount = static_cast<uint32_t>((1.0f - target.offset) * DUMMY_EDGE_TIME);

    traffic::RouteResponse final_res;
    final_res.total_time = res->total_weight + start_penalty - target_discount;
    final_res.path = std::move(res->path);
    
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
    uint32_t current_time = start_time;

    for (size_t i = 0; i < waypoints.size() - 1; ++i) {
        auto segment_res = RouteBetweenTwo(waypoints[i], waypoints[i+1], current_time);
        if (!segment_res) return segment_res;

        global_res.total_time += segment_res->total_time;
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
    if (!spatial_index_) return std::unexpected(std::string("Spatial index not loaded"));

    auto start_pt = spatial_index_->MapToEdge(src_x, src_y);
    auto target_pt = spatial_index_->MapToEdge(dst_x, dst_y);

    if (start_pt.edge_id == traffic::INVALID_NODE || target_pt.edge_id == traffic::INVALID_NODE) {
        return std::unexpected(std::string("Failed to map coordinates to graph"));
    }

    return RouteBetweenTwo(start_pt, target_pt, start_time);
}

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteMultipointByCoords(
    const std::vector<std::pair<float, float>>& coords, 
    uint32_t start_time
) {
    if (!spatial_index_) return std::unexpected(std::string("Spatial index not loaded"));
    if (coords.size() < 2) return std::unexpected(std::string("At least 2 coordinates required"));

    std::vector<traffic::RoutePoint> waypoints;
    waypoints.reserve(coords.size());

    for (const auto& cp : coords) {
        auto wp = spatial_index_->MapToEdge(cp.first, cp.second);
        if (wp.edge_id == traffic::INVALID_NODE) {
            return std::unexpected(std::format("Failed to map waypoint ({}, {}) to graph", cp.first, cp.second));
        }
        waypoints.push_back(wp);
    }

    return RouteMultipoint(waypoints, start_time);
}

} // namespace traffic::router::control
