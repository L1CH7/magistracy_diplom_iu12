#pragma once

#include <vector>
#include <cstdint>
#include <span>

#include "common/net/messages.hpp"
#include "common/net/typed_endpoint.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/route_arena.hpp"

namespace traffic::decision_engine
{

/**
 * @brief Management-by-Requirement (MPR) Engine.
 * Monitors agent progress and requests rerouting if significant delays are detected.
 * Designed for hardware-aligned zero-allocation hot cycles.
 */
class MprEngine
{
public:
    explicit MprEngine( traffic::common::net::TypedEndpoint< traffic::common::net::RouteRequest, traffic::common::net::RouteResponse > & router_endpoint )
    :   router_endpoint_( router_endpoint )
    {
        // Pre-reserve buffers to avoid allocations in the hot loop (warm-up phase)
        incoming_responses_.reserve( 1024 );
        outgoing_requests_.reserve( 1024 );
        stuck_indices_.reserve( 1024 );
    }

    /**
     * @brief Main MPR tick. Processes incoming routes and identifies agents needing rerouting.
     * @param current_time_sec Simulation time.
     * @param pool Agent properties.
     * @param arena Route and ETA storage.
     */
    void Tick( uint32_t current_time_sec, 
               data_provider::AgentPool & pool, 
               data_provider::RouteArena & arena )
    {
        // === PHASE 1: Receive and apply new routes (Cold Path) ===
        if( router_endpoint_.Receive( incoming_responses_ ) )
        {
            for( const auto & resp : incoming_responses_ )
            {
                if( resp.success && resp.agent_id < pool.Size() )
                {
                    arena.UpdateRoute( resp.agent_id, 
                                       std::span{ resp.path.data(), resp.path_len }, 
                                       std::span{ resp.edge_etas_sec.data(), resp.path_len } );
                    
                    // Reset agent progress on the new route
                    pool.route_progress_idx[ resp.agent_id ] = 0;
                    pool.edge_enter_time_sec[ resp.agent_id ] = current_time_sec;
                    
                    // Note: pool.current_edge will be updated by kinematics on transit
                    // or we could force it here if reroute happens mid-edge.
                    if( !resp.path.empty() )
                    {
                        pool.current_edge[ resp.agent_id ] = resp.path[ 0 ];
                    }
                }
            }
        }

        // === PHASE 2: Hot Path Scan for delayed agents (AVX2-friendly) ===
        // This loop is designed for auto-vectorization. No nested if-statements or complex logic.
        // Pre-fetching and cache-locality are maximized by linear SoA access.
        stuck_indices_.clear();
        const size_t agent_count = pool.Size();
        
        // Ensure buffers have enough capacity for the current pool size (one-time allocation if grows)
        if( stuck_indices_.capacity() < agent_count )
        {
            stuck_indices_.reserve( agent_count );
            outgoing_requests_.reserve( agent_count );
        }

        const uint8_t * __restrict active = pool.is_active.data();
        const uint32_t * __restrict enter_times = pool.edge_enter_time_sec.data();
        const uint16_t * __restrict progress_idxs = pool.route_progress_idx.data();

        #pragma GCC ivdep
        for( size_t i = 0; i < agent_count; ++i )
        {
            if( active[ i ] )
            {
                const uint32_t elapsed = current_time_sec - enter_times[ i ];
                
                // Fetch expected ETA from the arena. 
                // This is the only potentially non-linear access, but arena data is flat.
                const auto etas = arena.GetEtas( static_cast< uint32_t >( i ) );
                const uint32_t expected_eta = etas[ progress_idxs[ i ] ];

                const uint32_t allowed_time = ( expected_eta * TRAFFIC_MPR_TOLERANCE_NUM ) /
                                              TRAFFIC_MPR_TOLERANCE_DEN;
                if( elapsed > allowed_time )
                {
                    stuck_indices_.push_back( static_cast< uint32_t >( i ) );
                }
            }
        }

        // === PHASE 3: Prepare and send reroute requests ===
        outgoing_requests_.clear();
        for( uint32_t idx : stuck_indices_ )
        {
            // Populate request from agent's current state
            traffic::common::net::RouteRequest req{
                .agent_id = idx,
                .start_edge = pool.current_edge[ idx ],
                .target_edge = 0, // TODO: Store target_edge in AgentPool (Cold Data)
                .asf = 1,         // Default ASF
                .current_time_sec = current_time_sec
            };
            
            outgoing_requests_.push_back( std::move( req ) );
        }

        if( !outgoing_requests_.empty() )
        {
            router_endpoint_.Send( outgoing_requests_ );
        }
    }

private:
    traffic::common::net::TypedEndpoint< traffic::common::net::RouteRequest, traffic::common::net::RouteResponse > & router_endpoint_;

    // Reusable buffers to maintain Zero-Allocation status in the hot cycle
    std::vector< traffic::common::net::RouteResponse > incoming_responses_;
    std::vector< traffic::common::net::RouteRequest > outgoing_requests_;
    std::vector< uint32_t > stuck_indices_;
};

} // namespace traffic::decision_engine
