#pragma once

#include <random>
#include <vector>
#include <cstdint>

#include "data_provider/agent_pool.hpp"
#include "common/net/messages.hpp"

namespace traffic::data_provider
{

/**
 * @brief Utility for populating the simulation with agents and initial route requests.
 * Designed for hardware-aligned benchmarks and scenario setup.
 */
class ScenarioGenerator
{
public:
    /**
     * @brief Spawns a batch of agents with random start/target edges and generates initial requests.
     * @param pool Destination agent pool.
     * @param count Number of agents to spawn.
     * @param max_edges Range of EdgeIDs to pick from [0, max_edges).
     * @param default_asf Availability Search Factor for initial requests.
     * @param initial_requests Output buffer for route requests to be sent to the Router.
     */
    static void SpawnRandomAgents( AgentPool & pool, 
                                   uint32_t count, 
                                   uint32_t max_edges, 
                                   uint16_t default_asf, 
                                   std::vector< traffic::common::net::RouteRequest > & initial_requests )
    {
        // Zero-allocation setup: pre-allocate all SoA arrays in one go
        pool.Allocate( count );
        initial_requests.reserve( count );

        // Static PRNG to ensure continuity across calls in the same session
        static std::mt19937 gen{ std::random_device{}( ) };
        std::uniform_int_distribution< uint32_t > dist( 0, max_edges - 1 );

        for( uint32_t i = 0; i < count; ++i )
        {
            uint32_t start_edge = dist( gen );
            uint32_t target_edge = dist( gen );

            // Guarantee distinct endpoints for valid routing
            while( target_edge == start_edge )
            {
                target_edge = dist( gen );
            }

            // Populate SoA (Structure of Arrays)
            pool.is_active[ i ] = 1;
            pool.current_edge[ i ] = start_edge;
            pool.target_edge[ i ] = target_edge;
            pool.velocity_mps[ i ] = 15.0f; // Standard ~50 km/h
            pool.pos_meters[ i ] = 0.0f;
            pool.edge_enter_time_sec[ i ] = 0;
            pool.route_progress_idx[ i ] = 0;

            // Prepare Request POD for transmission
            traffic::common::net::RouteRequest req{
                .agent_id = i,
                .start_edge = start_edge,
                .target_edge = target_edge,
                .asf = default_asf,
                .current_time_sec = 0
            };

            initial_requests.push_back( std::move( req ) );
        }
    }
};

} // namespace traffic::data_provider
