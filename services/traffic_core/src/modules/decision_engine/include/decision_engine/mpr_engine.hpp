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
    explicit MprEngine( )
    {
        // Pre-reserve buffers to avoid allocations in the hot loop
        stuck_indices_.reserve( 1024 );
    }

    /**
     * @brief Main MPR tick. Processes incoming routes and identifies agents needing rerouting.
     * @param current_time_sec Simulation time.
     * @param pool Agent properties.
     * @param arena Route and ETA storage.
     * @param out_requests Buffer to fill with new reroute requests.
     */
    void Tick( uint32_t current_time_sec, 
               data_provider::AgentPool & pool, 
               data_provider::RouteArena & arena,
               std::vector< traffic::common::net::RouteRequest > & out_requests )
    {
        // === PHASE 1: Hot Path Scan for delayed agents (AVX2-friendly) ===
        stuck_indices_.clear();
        const size_t agent_count = pool.Size();
        
        if( stuck_indices_.capacity() < agent_count )
        {
            stuck_indices_.reserve( agent_count );
        }

        const uint8_t * __restrict active = pool.is_active.data();
        const uint32_t * __restrict enter_times = pool.edge_enter_time_sec.data();
        const uint16_t * __restrict progress_idxs = pool.route_progress_idx.data();

        #pragma GCC ivdep
        for( size_t i = 0; i < agent_count; ++i )
        {
            if( active[ i ] == 1 )  // Only truly active agents (not is_active=2 waiting-for-route)
            {
                const uint32_t elapsed = current_time_sec - enter_times[ i ];
                
                const auto etas = arena.GetEtas( static_cast< uint32_t >( i ) );
                if( etas.empty() || progress_idxs[ i ] + 1 >= etas.size() )
                    continue;

                const uint32_t current_eta = etas[ progress_idxs[ i ] ];
                const uint32_t next_eta = etas[ progress_idxs[ i ] + 1 ];
                const uint32_t expected_duration = next_eta > current_eta ? (next_eta - current_eta) : 1;

                const uint32_t allowed_time = ( expected_duration * TRAFFIC_MPR_TOLERANCE_NUM ) /
                                              TRAFFIC_MPR_TOLERANCE_DEN;
                if( elapsed > allowed_time )
                {
                    stuck_indices_.push_back( static_cast< uint32_t >( i ) );
                }
            }
        }

        // === PHASE 2: Prepare reroute requests ===
        for( uint32_t idx : stuck_indices_ )
        {
            traffic::common::net::RouteRequest req{
                .agent_id = idx,
                .start_edge = pool.current_edge[ idx ],
                .target_edge = pool.target_edge[ idx ],
                .asf = 1, // Default ASF for rerouting
                .current_time_sec = current_time_sec
            };
            
            out_requests.push_back( std::move( req ) );
        }
    }

private:
    // Reusable buffers to maintain Zero-Allocation status in the hot cycle
    std::vector< uint32_t > stuck_indices_;
};

} // namespace traffic::decision_engine
