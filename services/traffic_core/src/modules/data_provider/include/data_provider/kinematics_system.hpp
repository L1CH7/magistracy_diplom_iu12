#pragma once

#include <vector>
#include <cstdint>
#include <cstring>

#include "agent_pool.hpp"
#include "route_arena.hpp"

namespace traffic::data_provider
{

/**
 * @brief Zero-overhead simulation engine.
 * Implements hardware-optimized kinematic updates and topological transitions.
 */
class KinematicsSystem
{
public:
    KinematicsSystem( AgentPool & pool, RouteArena & arena )
    :   pool_( pool ),
        arena_( arena )
    {}

    /**
     * @brief Updates position for all active agents.
     * Uses SIMD-friendly loops and precalculated inverse lengths to maximize throughput.
     * @param dt Elapsed time in seconds.
     */
    void AdvanceKinematics( float dt ) noexcept
    {
        const size_t agent_count = pool_.Size();
        if( agent_count == 0 )
        {
            return;
        }

        // --- HOT PATH: Linear kinematics (SIMD vectorizable) ---
        // __restrict notifies the compiler that these arrays don't overlap,
        // allowing it to use AVX FMA instructions.
        float * __restrict pos = pool_.pos_meters.data();
        const float * __restrict vel = pool_.velocity_mps.data();
        const uint8_t * __restrict active = pool_.is_active.data();

        #pragma GCC ivdep
        for( size_t i = 0; i < agent_count; ++i )
        {
            if( active[ i ] )
            {
                pos[ i ] += vel[ i ] * dt;
            }
        }

        // --- COLD PATH FILTER: Identify agents crossing the edge boundary ---
        // Re-evaluating only the active ones without branches inside the loop if possible.
        const float * __restrict inv_len = pool_.inv_edge_length_m.data();
        pool_.transition_queue.clear();

        for( size_t i = 0; i < agent_count; ++i )
        {
            // pos * (1.0 / length) >= 1.0f means we reached the end of the edge.
            // This is equivalent to pos >= length but avoids division.
            if( active[ i ] && ( pos[ i ] * inv_len[ i ] >= 1.0f ) )
            {
                pool_.transition_queue.push_back( static_cast< uint32_t >( i ) );
            }
        }
    }

    /**
     * @brief Processes topological transitions for agents in the queue.
     * @param current_time_sec Current simulation time for arrival tracking.
     */
    void ProcessTransitions( uint32_t current_time_sec )
    {
        for( uint32_t agent_idx : pool_.transition_queue )
        {
            // Correct the "overflight" to start precisely at the beginning of the next edge
            // pos_meters -= length (where length = 1.0 / inv_len)
            pool_.pos_meters[ agent_idx ] -= ( 1.0f / pool_.inv_edge_length_m[ agent_idx ] );

            // Increment route progress
            uint16_t next_idx = ++pool_.route_progress_idx[ agent_idx ];
            auto route = arena_.GetRoute( agent_idx );

            if( next_idx < route.size() )
            {
                // Move to the next edge
                pool_.current_edge[ agent_idx ] = route[ next_idx ];
                pool_.edge_enter_time_sec[ agent_idx ] = current_time_sec;

                // TODO: Update inv_edge_length_m for the new edge from a graph cache.
                // For now, we assume the simulator will set it soon.
            }
            else
            {
                // End of journey: Despawn the agent
                pool_.is_active[ agent_idx ] = 0;
                pool_.pos_meters[ agent_idx ] = 0.0f; 
            }
        }
    }

private:
    AgentPool & pool_;
    RouteArena & arena_;
};

} // namespace traffic::data_provider
