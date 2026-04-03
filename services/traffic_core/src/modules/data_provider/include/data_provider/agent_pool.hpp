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
    std::vector< uint8_t > is_active;           // 1 for active, 0 for despawned/wait

    // === Buffer for agents finishing their current edge ===
    std::vector< uint32_t > transition_queue;

    /**
     * @brief Reservates and resizes all SoA vectors simultaneously.
     * @param capacity Initial number of agents.
     */
    void Allocate( size_t capacity )
    {
        pos_meters.resize( capacity, 0.0f );
        velocity_mps.resize( capacity, 0.0f );
        inv_edge_length_m.resize( capacity, 0.0f );

        current_edge.resize( capacity, 0 );
        route_progress_idx.resize( capacity, 0 );
        edge_enter_time_sec.resize( capacity, 0 );
        is_active.resize( capacity, 0 );

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
