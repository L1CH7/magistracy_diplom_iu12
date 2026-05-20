#pragma once

#include <vector>
#include <cstdint>
#include <cstring>
#include <atomic>
#include <cstdlib>

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
    std::atomic<uint32_t> * queue_volumes = nullptr;
    const traffic::PenaltyScale * k_magic = nullptr;

    // Static edge weights from the CSR graph (w_i = free-flow travel time in seconds).
    // Indexed directly by EdgeID. Non-owning ptr into mmap'd region.
    const traffic::EdgeWeight * static_weights = nullptr;

    // Precomputed per-edge physical lengths in meters, indexed by EdgeID.
    // nullptr = fallback to length / 15 m/s
    const float * edge_lengths_m = nullptr;

    // Pointer to mmap'd ExtendedAttributes array
    const ExtendedAttributes * edge_attributes = nullptr;

    uint32_t current_time_sec = 0;
    uint16_t asf = 1;
    std::vector<uint32_t>* completed_agents_out = nullptr;
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
    if( length_m < 0.1f ) length_m = 0.1f;

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

        // Penalty computation: scale by ASF because agents represent multiple cars
        uint64_t scaled_vol = static_cast< uint64_t >( current_vol ) * ctx.asf;
        uint32_t penalty = static_cast< uint32_t >( ( scale * scaled_vol * scaled_vol ) >> 20 );

        // Cap at 10x free-flow, same as TdAltRouter
        // Use float to avoid zero-cap for short edges (w < 1s)
        const float max_penalty = w * 10.0f;
        if( static_cast< float >( penalty ) > max_penalty )
            penalty = static_cast< uint32_t >( max_penalty );

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
    void AdvanceKinematics( float dt, const PhysicsContext & ctx = {} ) noexcept
    {
        const size_t agent_count = pool_.Size();
        if( agent_count == 0 )
        {
            return;
        }

        float * __restrict pos    = pool_.pos_meters.data();
        float * __restrict vel    = pool_.velocity_mps.data();
        const uint8_t * __restrict active = pool_.is_active.data();
        const traffic::EdgeID * __restrict current_edges = pool_.current_edge.data();
        const float * __restrict inv_len = pool_.inv_edge_length_m.data();

        for( size_t agent_idx = 0; agent_idx < agent_count; ++agent_idx )
        {
            if( active[ agent_idx ] != 1 )
            {
                continue;
            }

            traffic::EdgeID current_edge = current_edges[ agent_idx ];
            float edge_len = 1.0f / inv_len[ agent_idx ];

            // 1. Вычисляем длину физической очереди на ребре (с учетом ASF)
            uint32_t queue_size = 0;
            if( ctx.queue_volumes )
            {
                queue_size = ctx.queue_volumes[ current_edge ].load( std::memory_order_relaxed );
            }

            uint8_t lanes = 1;
            if( ctx.edge_attributes )
            {
                lanes = ctx.edge_attributes[ current_edge ].lanes;
                if( lanes == 0 ) lanes = 1;
            }

            float queue_length_m = static_cast<float>( queue_size * ctx.asf ) * 7.0f / static_cast<float>( lanes );

            // 2. Виртуальная стоп-линия (хвост пробки)
            float stop_line_m = std::max( 0.0f, edge_len - queue_length_m );

            // Определяем v_free_mps и v_discharge
            float w = ( ctx.static_weights )
                          ? static_cast< float >( ctx.static_weights[ current_edge ] )
                          : ( edge_len / 15.0f );
            if( w < 0.001f ) w = 0.001f;
            float v_free_mps = edge_len / w;

            // v_discharge = v_free * (C_vis / V_live)
            float v_discharge = v_free_mps;
            if( ctx.edge_attributes && ctx.live_volumes )
            {
                float C_vis = static_cast<float>( ctx.edge_attributes[ current_edge ].visual_capacity );
                float V_live = static_cast<float>( ctx.live_volumes[ current_edge ] * ctx.asf );
                if ( V_live > C_vis && V_live > 0.0f )
                {
                    v_discharge = v_free_mps * ( C_vis / V_live );
                }
            }
            if( v_discharge < 1.3f ) v_discharge = 1.3f; // Минимальная скорость выползания из пробки

            float agent_speed = v_free_mps;

            // 3. Кинематика (Двухрежимная)
            if ( !pool_.in_queue[ agent_idx ] && pos[ agent_idx ] < stop_line_m - 1.0f )
            {
                // РЕЖИМ 1: Свободный поток. Агент далеко от пробки, едет на V_free.
                agent_speed = v_free_mps;
                
                // Двигаем агента
                float new_pos = pos[ agent_idx ] + agent_speed * dt;
                
                // Если агент доехал до хвоста пробки в этом тике - он вступает в очередь
                if ( new_pos >= stop_line_m )
                {
                    pos[ agent_idx ] = stop_line_m; // Упирается в хвост
                    pool_.in_queue[ agent_idx ] = 1; // Помечаем, что агент вошел в пробку
                    if( ctx.queue_volumes )
                    {
                        ctx.queue_volumes[ current_edge ].fetch_add( 1, std::memory_order_relaxed );
                    }
                    vel[ agent_idx ] = v_discharge; // Задаем discharge скорость
                }
                else
                {
                    pos[ agent_idx ] = new_pos;
                    vel[ agent_idx ] = agent_speed;
                }
            }
            else
            {
                // РЕЖИМ 2: Очередь. Агент уже в пробке.
                agent_speed = v_discharge;
                
                // В очереди агент медленно ползет к финишу со скоростью вытекания
                pos[ agent_idx ] += agent_speed * dt;
                vel[ agent_idx ] = agent_speed;
            }
        }

        // --- COLD PATH FILTER: Identify agents crossing the edge boundary ---
        pool_.transition_queue.clear();
        for( size_t i = 0; i < agent_count; ++i )
        {
            if( active[ i ] == 1 && __builtin_expect( pos[ i ] * inv_len[ i ] >= 1.0f, 0 ) )
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
            bool blocked = false;
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

                    // Prefetch attributes and volumes of the subsequent edge in the route
                    if ( next_idx + 1 < route.size() )
                    {
                        traffic::EdgeID lookahead_edge = route[ next_idx + 1 ];
                        if ( ctx.edge_attributes )
                        {
                            __builtin_prefetch( &ctx.edge_attributes[ lookahead_edge ], 0, 3 );
                        }
                        if ( ctx.live_volumes )
                        {
                            __builtin_prefetch( &ctx.live_volumes[ lookahead_edge ], 1, 3 );
                        }
                    }

                    // --- LWR FLUID DYNAMICS SPILLBACK SYSTEM ---
                    uint32_t load_next = 0;
                    if ( ctx.live_volumes )
                    {
                        load_next = ctx.live_volumes[ next_edge ] * ctx.asf;
                    }
                    uint32_t jam_cap_next = 1;
                    uint32_t jam_cap_curr = 1;

                    if ( ctx.edge_attributes )
                    {
                        uint32_t raw_cap_next = ctx.edge_attributes[ next_edge ].jam_capacity;
                        // Apply micro-edge guard for next_edge
                        if ( __builtin_expect( raw_cap_next < ctx.asf, 0 ) )
                        {
                            raw_cap_next = ctx.asf;
                        }
                        jam_cap_next = std::max<uint32_t>( 1, raw_cap_next );

                        uint32_t raw_cap_curr = ctx.edge_attributes[ old_edge ].jam_capacity;
                        if ( __builtin_expect( raw_cap_curr < ctx.asf, 0 ) )
                        {
                            raw_cap_curr = ctx.asf;
                        }
                        jam_cap_curr = std::max<uint32_t>( 1, raw_cap_curr );
                    }

                    // 1. Check if the next edge is congested
                    if ( __builtin_expect( load_next + ctx.asf > jam_cap_next, 0 ) )
                    {
                        bool blocked_transition = true;
                        
                        // 2. ABSOLUTE PHYSICAL LIMIT (Eradicate 40x overloads permanently)
                        // Max 150% of physical capacity, with a minimum of +1 agent capacity for micro-edges
                        uint32_t absolute_max = jam_cap_next + std::max<uint32_t>( jam_cap_next / 2, ctx.asf );
                        
                        if ( load_next + ctx.asf <= absolute_max )
                        {
                            // 3. HYDRAULIC PRESSURE VALVE (Compare densities / pressure gradients)
                            uint32_t load_curr = 0;
                            if ( ctx.live_volumes )
                            {
                                load_curr = ctx.live_volumes[ old_edge ] * ctx.asf;
                            }
                            
                            float pressure_curr = static_cast<float>( load_curr ) / static_cast<float>( jam_cap_curr );
                            float pressure_next = static_cast<float>( load_next ) / static_cast<float>( jam_cap_next );
                            
                            // If pressure behind is greater or equal - allow transition chance (leak/squeeze)
                            if ( pressure_curr >= pressure_next )
                            {
                                float next_len = 25.0f; // fallback
                                if ( ctx.edge_attributes )
                                {
                                    next_len = ctx.edge_attributes[ next_edge ].length_m;
                                }
                                uint32_t leak_chance = ( next_len < 20.0f ) ? 15 : 5; // Higher leak chance for micro-edges
                                if ( static_cast<uint32_t>( std::rand() % 100 ) < leak_chance )
                                {
                                    blocked_transition = false; // Successfully squeezed through!
                                }
                            }
                        }
                        
                        if ( blocked_transition )
                        {
                            // Rollback transition. Agent remains at the very end of the current edge
                            pool_.route_progress_idx[ agent_idx ]--;
                            pool_.pos_meters[ agent_idx ] = edge_len - 0.05f; // 5 cm from the boundary
                            pool_.velocity_mps[ agent_idx ] = 0.0f; // Stopped in queue
                            blocked = true;
                            break; // Stop transitioning this agent
                        }
                    }

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
                    if( ctx.queue_volumes )
                    {
                        uint32_t q_vol = ctx.queue_volumes[ old_edge ].load( std::memory_order_relaxed );
                        if( q_vol > 0 )
                        {
                            ctx.queue_volumes[ old_edge ].fetch_sub( 1, std::memory_order_relaxed );
                        }
                    }

                    pool_.current_edge[ agent_idx ]        = next_edge;
                    pool_.edge_enter_time_sec[ agent_idx ] = ctx.current_time_sec;
                    pool_.in_queue[ agent_idx ]            = 0;

                    // Update geometry immediately so the while-condition re-evaluates correctly
                    float len = ( ctx.edge_lengths_m )
                                    ? ctx.edge_lengths_m[ next_edge ]
                                    : 1.0f;
                    if( len < 0.1f ) len = 0.1f;
                    pool_.inv_edge_length_m[ agent_idx ] = 1.0f / len;
                }
                else
                {
                    // End of route: despawn and update occupancy
                    if( ctx.live_volumes )
                    {
                        if( ctx.live_volumes[ old_edge ] > 0 )
                            ctx.live_volumes[ old_edge ]--;
                    }
                    if( ctx.queue_volumes )
                    {
                        uint32_t q_vol = ctx.queue_volumes[ old_edge ].load( std::memory_order_relaxed );
                        if( q_vol > 0 )
                        {
                            ctx.queue_volumes[ old_edge ].fetch_sub( 1, std::memory_order_relaxed );
                        }
                    }

                    pool_.is_active[ agent_idx ]  = 0;
                    pool_.pos_meters[ agent_idx ] = 0.0f;
                    pool_.in_queue[ agent_idx ]   = 0;
                    completed_agents++;
                    if (ctx.completed_agents_out) {
                        ctx.completed_agents_out->push_back(agent_idx);
                    }
                }
            }

            // Compute static Free-Flow speed ONCE for the edge the agent will actually dwell on.
            // Intermediate edges (passed through during multi-hop) are irrelevant.
            if( pool_.is_active[ agent_idx ] == 1 && !blocked )
            {
                traffic::EdgeID curr_edge = pool_.current_edge[ agent_idx ];
                float len = ( ctx.edge_lengths_m )
                                ? ctx.edge_lengths_m[ curr_edge ]
                                : ( 1.0f / pool_.inv_edge_length_m[ agent_idx ] );
                float w = ( ctx.static_weights )
                              ? static_cast< float >( ctx.static_weights[ curr_edge ] )
                              : ( len / 15.0f );
                if( w < 0.001f ) w = 0.001f;
                pool_.velocity_mps[ agent_idx ] = len / w;
            }
        }
        return completed_agents;
    }


private:
    AgentPool &  pool_;
    RouteArena & arena_;
};

} // namespace traffic::data_provider
