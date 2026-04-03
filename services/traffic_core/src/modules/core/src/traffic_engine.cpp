#include "core/traffic_engine.hpp"
#include "common/net/inproc_transport.hpp"
#include "data_provider/scenario_generator.hpp"
#include <iostream>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace traffic::core
{

using common::net::RouteRequest;
using common::net::RouteResponse;

TrafficEngine::TrafficEngine()
:   kin_system_( agent_pool_, route_arena_ ),
    router_pool_( TRAFFIC_ROUTER_THREADS, true, ( TRAFFIC_AVOID_OS_CORES != 0 ) )
{
}

TrafficEngine::~TrafficEngine()
{
    Stop();
}

std::expected< void, std::string > TrafficEngine::Init( const std::string & data_path )
{
    auto graph_status = router_manager_.LoadGraphs( data_path );
    if( !graph_status )
    {
        return std::unexpected( graph_status.error() );
    }

    auto mpr_transport = std::make_unique< common::net::InProcTransport >();
    auto router_transport = std::make_unique< common::net::InProcTransport >();
    mpr_transport->SetRemote( router_transport.get() );
    router_transport->SetRemote( mpr_transport.get() );

    mpr_ep_ = std::make_unique< common::net::TypedEndpoint< RouteRequest, RouteResponse > >( std::move( mpr_transport ) );
    router_ep_ = std::make_unique< common::net::TypedEndpoint< RouteResponse, RouteRequest > >( std::move( router_transport ) );

    mpr_engine_ = std::make_unique< decision_engine::MprEngine >( *mpr_ep_ );

    is_initialized_ = true;
    StartRouterWorker();

    return {};
}

void TrafficEngine::SpawnAgents( uint32_t num_agents, uint16_t asf )
{
    if( !is_initialized_ ) return;

    num_agents_ = num_agents;
    std::vector< RouteRequest > initial_requests;
    data_provider::ScenarioGenerator::SpawnRandomAgents( agent_pool_, num_agents, router_manager_.num_edges(), asf, initial_requests );

    for( uint32_t i = 0; i < num_agents; ++i )
    {
        uint32_t edge_id = agent_pool_.current_edge[ i ];
        float length = router_manager_.get_edge_length( edge_id );
        agent_pool_.inv_edge_length_m[ i ] = ( length > 0.001f ) ? ( 1.0f / length ) : 1.0f;
    }

    mpr_ep_->Send( initial_requests );
}

void TrafficEngine::Warmup()
{
    if( !is_initialized_ ) return;

    while( routes_computed_.load() < num_agents_ )
    {
        HandleResponses();
        std::this_thread::sleep_for( std::chrono::milliseconds( 1 ) );
    }
}

void TrafficEngine::Step( float dt )
{
    if( !is_initialized_ ) return;

    // Physics
    kin_system_.AdvanceKinematics( dt );
    kin_system_.ProcessTransitions( static_cast< uint32_t >( current_sim_time_ ) );

    // Decision Logic (1Hz)
    uint32_t sim_sec = static_cast< uint32_t >( current_sim_time_ );
    if( sim_sec > last_mpr_tick_sim_sec_ )
    {
        mpr_engine_->Tick( sim_sec, agent_pool_, route_arena_ );
        last_mpr_tick_sim_sec_ = sim_sec;
    }

    // Process responses from router
    HandleResponses();

    current_sim_time_ += dt;
}

void TrafficEngine::Stop()
{
    keep_running_ = false;
    if( router_worker_.joinable() )
    {
        router_worker_.join();
    }
}

void TrafficEngine::StartRouterWorker()
{
    router_worker_ = std::thread( [ this ]( ) {
        std::vector< RouteRequest > req_batch;
        std::vector< RouteResponse > res_batch;

        while( keep_running_ )
        {
            if( router_ep_->Receive( req_batch ) )
            {
                res_batch.resize( req_batch.size() );
                for( size_t i = 0; i < req_batch.size(); ++i )
                {
                    router_pool_.Enqueue( [ this, &req = req_batch[ i ], &res = res_batch[ i ] ]( ) {
                        auto result = router_manager_.Route< false, false >( 
                            req.start_edge, req.target_edge, req.current_time_sec 
                        );

                        res.agent_id = req.agent_id;
                        res.success = result.has_value();
                        if( res.success )
                        {
                            res.path_len = static_cast< uint16_t >( 
                                std::min< size_t >( result->path.size(), TRAFFIC_MAX_ROUTE_PATH ) 
                            );
                            for( uint16_t p = 0; p < res.path_len; ++p )
                            {
                                res.path[ p ] = result->path[ p ];
                                res.edge_etas_sec[ p ] = result->etas[ p ];
                            }
                        }
                    } );
                }

                router_pool_.WaitForAll();
                routes_computed_.fetch_add( req_batch.size(), std::memory_order_relaxed );
                router_ep_->Send( res_batch );
            }
            std::this_thread::yield();
        }
    } );
}

void TrafficEngine::HandleResponses()
{
    std::vector< RouteResponse > incoming_resps;
    if( mpr_ep_->Receive( incoming_resps ) )
    {
        for( const auto & r : incoming_resps )
        {
            if( r.success )
            {
                route_arena_.UpdateRoute( r.agent_id, 
                                          std::span{ r.path.data(), r.path_len }, 
                                          std::span{ r.edge_etas_sec.data(), r.path_len } );

                // During warmup, we might need to reset progress
                if( current_sim_time_ < 0.001f )
                {
                    agent_pool_.route_progress_idx[ r.agent_id ] = 0;
                    agent_pool_.edge_enter_time_sec[ r.agent_id ] = 0;
                }
            }
        }
    }
}

uint32_t TrafficEngine::GetActiveAgents() const
{
    uint32_t active = 0;
    for( uint32_t i = 0; i < agent_pool_.is_active.size(); ++i )
    {
        if( agent_pool_.is_active[ i ] ) active++;
    }
    return active;
}

} // namespace traffic::core
