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
#include <cstring>
#include <vector>
#include <format>

namespace traffic::router::control {

class RouterManager {
public:
    RouterManager();
    ~RouterManager();

    // Disable copy/move for safety with refs
    RouterManager(const RouterManager&) = delete;
    RouterManager& operator=(const RouterManager&) = delete;

    std::expected<void, std::string> LoadGraphs(const std::string& data_dir);
    
    // =========================================================================
    // 1. БАЗОВЫЙ МЕТОД: 2 точки по NodeID (Собственно вызов TdAltRouter)
    // =========================================================================
    template<bool TrafficEnabled = true, bool ProfileEnabled = false>
    std::expected<traffic::RoutingResult, std::string> Route(
        traffic::NodeID start_node, 
        traffic::NodeID target_node, 
        traffic::AbsoluteTime start_time = 0
    ) {
        if (!mapped_graph_.csr_region) return std::unexpected("Graphs not loaded");
        if (start_node == traffic::INVALID_NODE || target_node == traffic::INVALID_NODE) {
            return std::unexpected("Invalid NodeID provided");
        }

        const uint8_t* csr_ptr = static_cast<const uint8_t*>(mapped_graph_.csr_region->data());
        traffic::PointCount num_nodes;
        std::memcpy(&num_nodes, csr_ptr, sizeof(num_nodes));

        if (start_node >= num_nodes || target_node >= num_nodes) {
            return std::unexpected(std::format("Node out of bounds: max {}", num_nodes));
        }

        // Thread-local изоляция A* для конкурентных запросов
        thread_local std::unique_ptr<compute::TdAltRouter> tl_router = nullptr;
        if (!tl_router) {
            tl_router = std::make_unique<compute::TdAltRouter>(mapped_graph_.view, num_nodes);
            if (mapped_graph_.landmarks_region) {
                tl_router->get_heuristic().set_landmarks(static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()));
            }
        }
        
        const traffic::PenaltyScale* k_magic_ptr = mapped_graph_.kmagic_region ? 
            static_cast<const traffic::PenaltyScale*>(mapped_graph_.kmagic_region->data()) : nullptr;
        
        auto result = tl_router->Route<TrafficEnabled, ProfileEnabled>(
            start_node, target_node, start_time, 
            volume_manager_ ? volume_manager_->data() : nullptr,
            k_magic_ptr, 
            nullptr // mpr_penalty 
        );

        // Обработка разрыва графа (отсутствие пути)
        if (result.total_weight == traffic::INF_WEIGHT && start_node != target_node) {
            return std::unexpected(std::format("Route disconnected between {} and {}", start_node, target_node));
        }

        return result;
    }

    // =========================================================================
    // 2. ПЕРЕГРУЗКА: 2 точки по Координатам (Lat/Lon)
    // =========================================================================
    template<bool TrafficEnabled = true, bool ProfileEnabled = false>
    std::expected<traffic::RoutingResult, std::string> Route(
        float lon1, float lat1, float lon2, float lat2, 
        traffic::AbsoluteTime start_time = 0
    ) {
        if (!spatial_grid_) return std::unexpected("Spatial grid not loaded");

        auto start_pt = spatial_grid_->MapToEdge(lon1, lat1);
        auto target_pt = spatial_grid_->MapToEdge(lon2, lat2);

        if (start_pt.edge_id == traffic::INVALID_NODE) return std::unexpected(std::format("Start coord ({}, {}) not found on graph", lon1, lat1));
        if (target_pt.edge_id == traffic::INVALID_NODE) return std::unexpected(std::format("Target coord ({}, {}) not found on graph", lon2, lat2));

        return Route<TrafficEnabled, ProfileEnabled>(start_pt.edge_id, target_pt.edge_id, start_time);
    }

    // =========================================================================
    // 3. ПЕРЕГРУЗКА: Multipoint по массиву NodeID
    // =========================================================================
    template<bool TrafficEnabled = true, bool ProfileEnabled = false>
    std::expected<traffic::RoutingResult, std::string> Route(
        const std::vector<traffic::NodeID>& waypoints, 
        traffic::AbsoluteTime start_time = 0
    ) {
        if (waypoints.empty()) return std::unexpected("Waypoints array is empty");
        if (waypoints.size() == 1) return Route<TrafficEnabled, ProfileEnabled>(waypoints[0], waypoints[0], start_time);
        
        traffic::RoutingResult total_result;
        total_result.total_weight = 0;
        traffic::AbsoluteTime current_time = start_time;
        
        for (size_t i = 0; i < waypoints.size() - 1; ++i) {
            auto res = Route<TrafficEnabled, ProfileEnabled>(waypoints[i], waypoints[i+1], current_time);
            
            // Если сегмент недостижим или возникла ошибка, прокидываем её наверх
            if (!res) return std::unexpected(std::format("Multipoint segment [{}] failed: {}", i, res.error()));
            
            total_result.total_weight += res->total_weight;
            total_result.visited_nodes_count += res->visited_nodes_count;
            total_result.route_cycles += res->route_cycles;
            
            if (i == 0) {
                total_result.path = std::move(res->path);
                total_result.etas = std::move(res->etas);
            } else {
                // Избегаем дублирования узла-стыка (waypoints[i])
                if (!res->path.empty()) {
                    total_result.path.insert(total_result.path.end(), res->path.begin() + 1, res->path.end());
                    total_result.etas.insert(total_result.etas.end(), res->etas.begin() + 1, res->etas.end());
                }
            }
            // Время старта для следующего сегмента = время прибытия в конец текущего
            if (!total_result.etas.empty()) {
                current_time = total_result.etas.back(); 
            }
        }
        return total_result;
    }

    // =========================================================================
    // 4. ПЕРЕГРУЗКА: Multipoint по массиву Координат (Lat/Lon)
    // =========================================================================
    template<bool TrafficEnabled = true, bool ProfileEnabled = false>
    std::expected<traffic::RoutingResult, std::string> Route(
        const std::vector<std::pair<float, float>>& coords, 
        traffic::AbsoluteTime start_time = 0
    ) {
        if (!spatial_grid_) return std::unexpected("Spatial grid not loaded");
        if (coords.empty()) return std::unexpected("Coordinate array is empty");

        std::vector<traffic::NodeID> waypoints;
        waypoints.reserve(coords.size());

        for (size_t i = 0; i < coords.size(); ++i) {
            auto wp = spatial_grid_->MapToEdge(coords[i].first, coords[i].second);
            if (wp.edge_id == traffic::INVALID_NODE) {
                return std::unexpected(std::format("Failed to map coordinate index {} ({}, {})", i, coords[i].first, coords[i].second));
            }
            waypoints.push_back(wp.edge_id);
        }

        return Route<TrafficEnabled, ProfileEnabled>(waypoints, start_time);
    }

    const uint16_t* get_landmarks_ptr() const {
        return (mapped_graph_.landmarks_region) ? 
            static_cast<const uint16_t*>(mapped_graph_.landmarks_region->data()) : nullptr;
    }

    const traffic::PenaltyScale* get_kmagic_ptr() const {
        return (mapped_graph_.kmagic_region) ? 
            static_cast<const traffic::PenaltyScale*>(mapped_graph_.kmagic_region->data()) : nullptr;
    }

    const traffic::GraphView& get_view() const { return mapped_graph_.view; }

    const common::GeometryStore* get_geometry_store() const { return mapped_graph_.geometry_store.get(); }

    int64_t get_osm_id(traffic::NodeID edge_id) const {
        if (!mapped_graph_.osm_ids_region || edge_id >= num_nodes()) return -1;
        return static_cast<const int64_t*>(mapped_graph_.osm_ids_region->data())[edge_id];
    }

    /**
     * @brief Вернуть вместимость ребра (кол-во машин) по запечённым lanes, length_m и speed_kmh.
     *
     * Формула динамического слота (Правило N секунд):
     *   slot_m = CAR_LENGTH_M + (speed_mps * safe_time_sec)
     *   capacity = floor(length_m / slot_m) * lanes
     *
     * Пороги и константы задаются через cmake/options.cmake:
     *   TRAFFIC_CAR_LENGTH_M, TRAFFIC_SAFE_TIME_{HIGHWAY,URBAN,DENSE}_SEC,
     *   TRAFFIC_SPEED_{HIGHWAY,DENSE}_KMH, TRAFFIC_DEFAULT_LANES
     *
     * Структура attributes.bin per-node (stride=28 байт, заголовок 8 байт):
     *   offset 0: float  speed_kmh
     *   offset 4: uint8  lanes
     *   offset 5: uint8  highway_class
     *   offset 6: uint8  oneway
     *   offset 7: uint8  pad
     *   offset 8: float  length_m
     *   offset 12: float t_free_base
     *   offset 16: int32 k_magic
     *   offset 20: float min_x
     *   offset 24: float min_y
     */
    [[nodiscard]] uint32_t get_edge_capacity(traffic::NodeID edge_id) const noexcept {
        // Compile-time constants from cmake/options.cmake
#ifndef TRAFFIC_CAR_LENGTH_M
#  define TRAFFIC_CAR_LENGTH_M 7
#endif
#ifndef TRAFFIC_SAFE_TIME_HIGHWAY_SEC
#  define TRAFFIC_SAFE_TIME_HIGHWAY_SEC 3
#endif
#ifndef TRAFFIC_SAFE_TIME_URBAN_SEC
#  define TRAFFIC_SAFE_TIME_URBAN_SEC 2
#endif
#ifndef TRAFFIC_SAFE_TIME_DENSE_SEC
#  define TRAFFIC_SAFE_TIME_DENSE_SEC 15   // x10: 1.5 sec
#endif
#ifndef TRAFFIC_SPEED_HIGHWAY_KMH
#  define TRAFFIC_SPEED_HIGHWAY_KMH 90
#endif
#ifndef TRAFFIC_SPEED_DENSE_KMH
#  define TRAFFIC_SPEED_DENSE_KMH 40
#endif
#ifndef TRAFFIC_DEFAULT_LANES
#  define TRAFFIC_DEFAULT_LANES 1
#endif
        constexpr float  CAR_LEN_M        = static_cast<float>(TRAFFIC_CAR_LENGTH_M);
        constexpr float  T_HIGHWAY        = static_cast<float>(TRAFFIC_SAFE_TIME_HIGHWAY_SEC);
        constexpr float  T_URBAN          = static_cast<float>(TRAFFIC_SAFE_TIME_URBAN_SEC);
        constexpr float  T_DENSE          = static_cast<float>(TRAFFIC_SAFE_TIME_DENSE_SEC) / 10.0f;
        constexpr float  SPD_HIGHWAY      = static_cast<float>(TRAFFIC_SPEED_HIGHWAY_KMH);
        constexpr float  SPD_DENSE        = static_cast<float>(TRAFFIC_SPEED_DENSE_KMH);
        constexpr uint8_t DEF_LANES       = static_cast<uint8_t>(TRAFFIC_DEFAULT_LANES);

        constexpr size_t HEADER_SIZE  = 8;   // num_nodes(4) + num_edges(4)
        constexpr size_t NODE_STRIDE  = 28;
        constexpr size_t SPD_OFFSET   = 0;
        constexpr size_t LANES_OFFSET = 4;
        constexpr size_t LEN_OFFSET   = 8;

        if (!mapped_graph_.attributes_region || edge_id >= num_nodes()) return 1u;
        const uint8_t* ptr = static_cast<const uint8_t*>(mapped_graph_.attributes_region->data())
                             + HEADER_SIZE + edge_id * NODE_STRIDE;

        float speed_kmh = 0.0f;
        std::memcpy(&speed_kmh, ptr + SPD_OFFSET, sizeof(float));

        uint8_t lanes = ptr[LANES_OFFSET];
        if (lanes == 0) lanes = DEF_LANES;

        float length_m = 0.0f;
        std::memcpy(&length_m, ptr + LEN_OFFSET, sizeof(float));
        if (length_m <= 0.0f) return static_cast<uint32_t>(lanes);

        // Правило N секунд: безопасная дистанция зависит от скоростного режима
        float safe_t = T_URBAN;
        if      (speed_kmh >= SPD_HIGHWAY) safe_t = T_HIGHWAY;
        else if (speed_kmh <= SPD_DENSE)   safe_t = T_DENSE;

        float speed_mps   = speed_kmh / 3.6f;
        float slot_m      = CAR_LEN_M + speed_mps * safe_t;
        uint32_t cap      = static_cast<uint32_t>(length_m / slot_m) * lanes;
        return std::max<uint32_t>(cap, 1u);
    }

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

    // Получить длину ребра для физики Симулятора
    [[nodiscard]] inline float get_edge_length(traffic::NodeID edge_id) const noexcept {
        if (!mapped_graph_.geometry_store) return 0.0f;
        auto geom = mapped_graph_.geometry_store->get_geometry(edge_id);
        if (geom.points.empty()) return 0.0f;
        return geom.accum_lens.back();
    }
    
    // Прямой доступ к менеджеру корзинок для Симулятора
    traffic::router::control::VolumeManager* get_volume_manager() noexcept { return volume_manager_.get(); }

    /**
     * @brief Построить кэш центроидов рёбер из SpatialGrid (однократно при старте).
     * @return unordered_map<EdgeID, pair<lon, lat>>
     */
    [[nodiscard]] std::unordered_map<traffic::EdgeID, std::pair<float, float>>
    BuildEdgeCentroidCache() const noexcept
    {
        if ( spatial_grid_ ) return spatial_grid_->BuildEdgeCentroidCache();
        return {};
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
