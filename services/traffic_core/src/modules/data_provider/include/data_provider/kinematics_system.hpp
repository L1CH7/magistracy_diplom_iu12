#pragma once

#include <vector>
#include <cstdint>
#include <cstring>
#include <atomic>

#include "agent_pool.hpp"
#include "route_arena.hpp"
#include "common/graph_types.hpp"

namespace traffic::data_provider
{

/**
 * @brief Lightweight context for physics calculations at edge transitions.
 * All pointers are non-owning. Passed by value into ProcessTransitions.
 */
struct PhysicsContext
{
    // Live physical occupancy data (updated by KinematicsSystem during transitions)
    uint32_t * live_volumes = nullptr;
    uint32_t * max_volumes  = nullptr;
    const traffic::PenaltyScale * k_magic = nullptr;

    // Static edge weights from the CSR graph (w_i = free-flow travel time in seconds).
    // Indexed directly by EdgeID. Non-owning ptr into mmap'd region.
    const traffic::EdgeWeight * static_weights = nullptr;

    // Precomputed per-edge physical lengths in meters, indexed by EdgeID.
    // nullptr = fallback to length / 15 m/s
    const float * edge_lengths_m = nullptr;

    uint32_t current_time_sec = 0;
};

/**
 * @brief Computes the effective velocity for an agent entering an edge.
 * Mirrors the BPR logic in TdAltRouter hot-path exactly.
 * Called ONCE at edge entry, not every tick.
 * @param edge_id  The edge the agent is entering.
 * @param ctx      Physics context (buckets, k_magic, static weights, lengths).
 * @param length_m Physical length of the edge in meters.
 * @return Effective velocity in m/s.
 */
[[nodiscard]] inline float ComputeEdgeEntrySpeed(
    traffic::EdgeID       edge_id,
    const PhysicsContext & ctx,
    float                 length_m ) noexcept
{
    // w = static free-flow weight in seconds.
    // Matches TdAltRouter: the CSR `w` IS the free-flow travel time.
    float w = ( ctx.static_weights )
                  ? static_cast< float >( ctx.static_weights[ edge_id ] )
                  : ( length_m / 15.0f ); // fallback: assume 15 m/s free-flow

    if( w < 0.001f ) w = 0.001f; // guard zero-weight edges

    if( ctx.live_volumes && ctx.k_magic )
    {
        uint32_t current_vol = ctx.live_volumes[ edge_id ];
        uint64_t scale       = static_cast< uint64_t >( ctx.k_magic[ edge_id ] );

        // Penalty computation directly from current physical volume
        uint32_t penalty = static_cast< uint32_t >( ( scale * current_vol * current_vol ) >> 20 );

        // Cap at 10x free-flow, same as TdAltRouter
        uint32_t w_sec = static_cast< uint32_t >( w );
        if( penalty > w_sec * 10 )
            penalty = w_sec * 10;

        w += static_cast< float >( penalty );
    }

    return length_m / w;
}

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
        // __restrict tells the compiler these arrays don't alias,
        // enabling AVX FMA vectorization.
        float * __restrict pos    = pool_.pos_meters.data();
        const float * __restrict vel    = pool_.velocity_mps.data();
        const uint8_t * __restrict active = pool_.is_active.data();

        // Hot path: only is_active==1 agents move (is_active==2 = waiting for route).
        #pragma GCC ivdep
        for( size_t i = 0; i < agent_count; ++i )
        {
            if( active[ i ] == 1 )
            {
                pos[ i ] += vel[ i ] * dt;
            }
        }

        // --- COLD PATH FILTER: Identify agents crossing the edge boundary ---
        const float * __restrict inv_len = pool_.inv_edge_length_m.data();
        pool_.transition_queue.clear();

        for( size_t i = 0; i < agent_count; ++i )
        {
            // Only is_active==1 agents can transition (not waiting-for-route agents).
            if( active[ i ] == 1 && ( pos[ i ] * inv_len[ i ] >= 1.0f ) )
            {
                pool_.transition_queue.push_back( static_cast< uint32_t >( i ) );
            }
        }
    }

    /**
     * @brief Processes topological transitions for agents in the queue.
     *
     * Key fix vs previous version:
     *  - inv_edge_length_m is now updated immediately when agent enters next edge.
     *  - BPR velocity is computed ONCE at edge entry (O(transitions), not O(agents*ticks)).
     *
     * - [x] Update `kinematics_system.hpp`
     * - [x] Add `max_volumes` to `PhysicsContext` struct
     * - [x] Update peak volumes in `ProcessTransitions()` during edge hops
     *
     * @param ctx Physics context for BPR speed and geometry lookup.
     * @return Number of agents that completed their route this tick.
     */
    uint32_t ProcessTransitions( const PhysicsContext & ctx )
    {
        uint32_t completed_agents = 0;
        for( uint32_t agent_idx : pool_.transition_queue )
        {
            // --- Multi-hop loop ---
            // With large acceleration (dt >> edge_length/velocity), an agent can overshoot
            // multiple edges in a single tick. We drain the overshoot here in one call
            // rather than wasting N ticks on N hops at 1 hop/tick.
            while( pool_.is_active[ agent_idx ] == 1 &&
                   pool_.pos_meters[ agent_idx ] * pool_.inv_edge_length_m[ agent_idx ] >= 1.0f )
            {
                // Subtract the current edge length to correct the overshoot
                float edge_len = 1.0f / pool_.inv_edge_length_m[ agent_idx ];
                pool_.pos_meters[ agent_idx ] -= edge_len;
                if( pool_.pos_meters[ agent_idx ] < 0.0f )
                    pool_.pos_meters[ agent_idx ] = 0.0f;

                uint16_t next_idx = ++pool_.route_progress_idx[ agent_idx ];
                auto route        = arena_.GetRoute( agent_idx );
                traffic::EdgeID old_edge = pool_.current_edge[ agent_idx ];

                if( next_idx < route.size() )
                {
                    traffic::EdgeID next_edge = route[ next_idx ];

                    // Check if we reached a waypoint
                    if( pool_.next_waypoint_idx[ agent_idx ] < pool_.total_waypoints[ agent_idx ] &&
                        next_edge == pool_.waypoints[ agent_idx ][ pool_.next_waypoint_idx[ agent_idx ] ] )
                    {
                        pool_.next_waypoint_idx[ agent_idx ]++;
                    }

                    // Update physical occupancy counters
                    if( ctx.live_volumes )
                    {
                        if( ctx.live_volumes[ old_edge ] > 0 )
                            ctx.live_volumes[ old_edge ]--;
                        ctx.live_volumes[ next_edge ]++;
                        if( ctx.max_volumes && ctx.live_volumes[ next_edge ] > ctx.max_volumes[ next_edge ] )
                            ctx.max_volumes[ next_edge ] = ctx.live_volumes[ next_edge ];
                    }

                    pool_.current_edge[ agent_idx ]        = next_edge;
                    pool_.edge_enter_time_sec[ agent_idx ] = ctx.current_time_sec;

                    // Update geometry immediately so the while-condition re-evaluates correctly
                    float len = ( ctx.edge_lengths_m )
                                    ? ctx.edge_lengths_m[ next_edge ]
                                    : 1.0f;
                    pool_.inv_edge_length_m[ agent_idx ] = ( len > 0.001f ) ? ( 1.0f / len ) : 1.0f;
                }
                else
                {
                    // End of route: despawn and update occupancy
                    if( ctx.live_volumes )
                    {
                        if( ctx.live_volumes[ old_edge ] > 0 )
                            ctx.live_volumes[ old_edge ]--;
                    }

                    pool_.is_active[ agent_idx ]  = 0;
                    pool_.pos_meters[ agent_idx ] = 0.0f;
                    completed_agents++;
                }
            }

            // Compute BPR speed ONCE for the edge the agent will actually dwell on.
            // Intermediate edges (passed through during multi-hop) are irrelevant.
            if( pool_.is_active[ agent_idx ] == 1 )
            {
                traffic::EdgeID curr_edge = pool_.current_edge[ agent_idx ];
                float len = ( ctx.edge_lengths_m )
                                ? ctx.edge_lengths_m[ curr_edge ]
                                : ( 1.0f / pool_.inv_edge_length_m[ agent_idx ] );
                pool_.velocity_mps[ agent_idx ] = ComputeEdgeEntrySpeed( curr_edge, ctx, len );
            }
        }
        return completed_agents;
    }


private:
    AgentPool &  pool_;
    RouteArena & arena_;
};

} // namespace traffic::data_provider
