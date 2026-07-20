#pragma once

#include <vector>
#include <cstdint>

#include "common/graph_types.hpp"

namespace traffic::data_provider
{

/**
 * @brief Strict SoA (Structure of Arrays) container for agent properties.
 * Designed to maximize L1 cache hits and SIMD throughput.
 * Data is partitioned by access frequency: Hot (kinematics), Warm (state), and Cold.
 */
struct AgentPool
{
    // === Hot Data (Accessed in every tick for every agent) ===
    std::vector< float > pos_meters;            // Distance traveled along current edge [m]
    std::vector< float > velocity_mps;          // Speed [m/s]
    std::vector< float > inv_edge_length_m;     // 1.0f / length. Precalculated to replace divisions.

    // === Warm/Cold Data (Accessed during edge transitions or M-PR checks) ===
    std::vector< traffic::EdgeID > current_edge; // Edge we are currently on
    std::vector< uint16_t > route_progress_idx;  // Index in agent's own RouteSpan
    std::vector< uint32_t > edge_enter_time_sec; // Arrival time to current edge
    std::vector< std::array< traffic::EdgeID, 16 > > waypoints;
    std::vector< uint8_t > total_waypoints;
    std::vector< uint8_t > next_waypoint_idx; // Индекс точки, к которой агент едет сейчас
    std::vector< uint8_t > is_active;           // 1 for active, 0 for despawned/wait
    std::vector< uint8_t > is_waiting_route;   // true if agent has an active reroute request
    std::vector< uint8_t > in_queue;           // 1 = в очереди, 0 = в свободном потоке
    std::vector< uint32_t > route_epoch;       // Current routing epoch to filter stale responses

    // === Поля населения и связности поездок (Zero-Teleportation Home/Work) ===
    std::vector< traffic::EdgeID > home_edge;    // Исходное ребро дома (для Commuters)
    std::vector< traffic::EdgeID > work_edge;    // Исходное ребро работы (для Commuters)
    std::vector< uint8_t > population_type;      // Тип населения (0: Commuter, 1: Commercial, 2: PublicTransport, 3: Random)
    std::vector< float > schedule_offset_sec;    // Гауссово смещение индивидуального расписания выезда

    // === Buffer for agents finishing their current edge ===
    std::vector< uint32_t > transition_queue;

    /**
     * @brief Резервирует и масштабирует все SoA векторы одновременно.
     * @param capacity Исходное количество агентов.
     */
    void Allocate( size_t capacity )
    {
        pos_meters.assign( capacity, 0.0f );
        velocity_mps.assign( capacity, 0.0f );
        inv_edge_length_m.assign( capacity, 0.0f );

        current_edge.assign( capacity, 0 );
        route_progress_idx.assign( capacity, 0 );
        edge_enter_time_sec.assign( capacity, 0 );
        waypoints.resize( capacity );
        total_waypoints.assign( capacity, 0 );
        next_waypoint_idx.assign( capacity, 0 );
        is_active.assign( capacity, 0 );
        is_waiting_route.assign( capacity, 0 );
        in_queue.assign( capacity, 0 );
        route_epoch.assign( capacity, 0 );

        home_edge.assign( capacity, 0 );
        work_edge.assign( capacity, 0 );
        population_type.assign( capacity, 0 );
        schedule_offset_sec.assign( capacity, 0.0f );

        // Initial capacity for transitions to avoid allocations during tick
        transition_queue.reserve( capacity / 10 );
    }

    /**
     * @brief Returns the number of currently allocated agent slots.
     */
    [[nodiscard]] size_t Size() const noexcept
    {
        return pos_meters.size();
    }
};

} // namespace traffic::data_provider
