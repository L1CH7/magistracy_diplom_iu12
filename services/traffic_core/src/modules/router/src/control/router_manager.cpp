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

std::expected<traffic::RouteResponse, std::string> RouterManager::RouteBetweenTwo(
    traffic::RoutePoint start, 
    traffic::RoutePoint target, 
    uint32_t start_time
) {

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
    // Используем Route<true, true> (Трафик включен, Профилирование включено для аналитики)
    auto res = Route<true, true>(start.edge_id, target.edge_id, start_time);
    if (!res) return std::unexpected(res.error());

    // 3. Корректировка времени (Partial Edges)
    uint32_t start_penalty = static_cast<uint32_t>((1.0f - start.offset) * start_time_full);
    uint32_t target_discount = static_cast<uint32_t>((1.0f - target.offset) * target_time_full);

    traffic::RouteResponse final_res;
    final_res.total_time = res->total_weight + start_penalty - target_discount;
    final_res.total_visited_nodes = res->visited_nodes_count;
    final_res.total_cycles = res->route_cycles;
    final_res.path = std::move(res->path);
    final_res.etas = std::move(res->etas);
    
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
        global_res.total_visited_nodes += segment_res->total_visited_nodes;
        global_res.total_cycles += segment_res->total_cycles;
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


template<bool TrafficEnabled, bool ProfileEnabled>
std::expected<traffic::RoutingResult, std::string> RouterManager::Route(
    traffic::NodeID start_node_idx, 
    traffic::NodeID target_node_idx, 
    traffic::AbsoluteTime start_time
) {
    if (!mapped_graph_.csr_region) return std::unexpected(std::string("Graphs not loaded"));

    const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
    traffic::PointCount num_nodes;
    std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));

    thread_local std::unique_ptr<TdAltRouter> tl_router = nullptr;
    if (!tl_router) {
        tl_router = std::make_unique<TdAltRouter>(mapped_graph_.view, num_nodes);
        if (mapped_graph_.landmarks_region) {
            tl_router->get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()));
        }
    }
    
    if (start_node_idx >= num_nodes || target_node_idx >= num_nodes) {
        return std::unexpected(std::format("Node out of range"));
    }

    // Извлекаем массивы для расчета заторов с использованием глобального типа PenaltyScale
    const traffic::PenaltyScale* k_magic_ptr = mapped_graph_.kmagic_region ? 
        static_cast<const traffic::PenaltyScale*>(mapped_graph_.kmagic_region->data()) : nullptr;
        
    return tl_router->Route<TrafficEnabled, ProfileEnabled>(
        start_node_idx, target_node_idx, start_time, 
        volume_manager_ ? volume_manager_->data() : nullptr,
        k_magic_ptr, 
        nullptr 
    );
}

// Явные инстанциации всех 4 комбинаций шаблона
template std::expected<traffic::RoutingResult, std::string> RouterManager::Route<true, true>(traffic::NodeID, traffic::NodeID, traffic::AbsoluteTime);
template std::expected<traffic::RoutingResult, std::string> RouterManager::Route<true, false>(traffic::NodeID, traffic::NodeID, traffic::AbsoluteTime);
template std::expected<traffic::RoutingResult, std::string> RouterManager::Route<false, true>(traffic::NodeID, traffic::NodeID, traffic::AbsoluteTime);
template std::expected<traffic::RoutingResult, std::string> RouterManager::Route<false, false>(traffic::NodeID, traffic::NodeID, traffic::AbsoluteTime);

} // namespace traffic::router::control
