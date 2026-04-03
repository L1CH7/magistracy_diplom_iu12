#include "core/traffic_engine.hpp"
#include "common/net/inproc_transport.hpp"
#include "data_provider/scenario_generator.hpp"

#include <iostream>
#include <memory>
#include <thread>
#include <atomic>
#include <vector>
#include <string>
#include <cstdint>
#include <expected>
#include <sstream>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace traffic::core
{

using traffic::common::net::RouteRequest;
using traffic::common::net::RouteResponse;

TrafficEngine::TrafficEngine()
:   is_initialized_( false ),
    keep_running_( true ),
    num_agents_( 0 ),
    current_sim_time_( 0.0f ),
    last_mpr_tick_sim_sec_( 0 ),
    routes_computed_( 0 ),
    router_pool_( TRAFFIC_ROUTER_THREADS, true ),
    kin_system_( agent_pool_, route_arena_ )
{
    mpr_requests_buffer_.reserve( 4096 );
}

TrafficEngine::TrafficEngine( const std::vector< int > & router_cores )
:   is_initialized_( false ),
    keep_running_( true ),
    num_agents_( 0 ),
    current_sim_time_( 0.0f ),
    last_mpr_tick_sim_sec_( 0 ),
    routes_computed_( 0 ),
    router_pool_( router_cores ),
    kin_system_( agent_pool_, route_arena_ )
{
    mpr_requests_buffer_.reserve( 4096 );
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

    // Link transports for zero-copy in-process communication
    mpr_transport->SetRemote( router_transport.get() );
    router_transport->SetRemote( mpr_transport.get() );

    mpr_ep_ = std::make_unique< common::net::TypedEndpoint< RouteRequest, RouteResponse > >( std::move( mpr_transport ) );
    router_ep_ = std::make_unique< common::net::TypedEndpoint< RouteResponse, RouteRequest > >( std::move( router_transport ) );

    mpr_engine_ = std::make_unique< decision_engine::MprEngine >();

    is_initialized_ = true;
    StartRouterWorker();

    return {};
}

void TrafficEngine::SpawnAgents( uint32_t num_agents, uint16_t asf )
{
    if( !is_initialized_ ) return;

    num_agents_ = num_agents;
    std::vector< RouteRequest > initial_requests;
    
    data_provider::ScenarioGenerator::SpawnRandomAgents( 
        agent_pool_, 
        num_agents, 
        static_cast< uint32_t >( router_manager_.num_edges() ), 
        asf, 
        initial_requests 
    );

    agent_pool_.Allocate( num_agents );
    // RouteArena resizes automatically in UpdateRoute

    // Send initial paths computation
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

    // Phase 1: Locomotion (Kinematics + Collision Avoidance)
    kin_system_.AdvanceKinematics( dt );
    kin_system_.ProcessTransitions( static_cast< uint32_t >( current_sim_time_ ) );

    // Phase 2: Decision Making (MPR - Mesoscopic Path Rerouting)
    uint32_t sim_sec = static_cast< uint32_t >( current_sim_time_ );
    if( sim_sec > last_mpr_tick_sim_sec_ )
    {
        mpr_requests_buffer_.clear();
        mpr_engine_->Tick( sim_sec, agent_pool_, route_arena_, mpr_requests_buffer_ );

        if( !mpr_requests_buffer_.empty() )
        {
            mpr_ep_->Send( mpr_requests_buffer_ );
        }
        last_mpr_tick_sim_sec_ = sim_sec;
    }

    current_sim_time_ += dt;

    // Phase 3: Route Integration (Apply responses to Route Arena)
    HandleResponses();
}

void TrafficEngine::ForceReroute( const std::vector< RouteRequest > & requests )
{
    if( !is_initialized_ || requests.empty() ) return;
    mpr_ep_->Send( requests );
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
#ifdef __linux__
        cpu_set_t cpuset;
        CPU_ZERO( &cpuset );
        CPU_SET( TRAFFIC_DISPATCH_AFFINITY, &cpuset );
        pthread_setaffinity_np( pthread_self(), sizeof( cpu_set_t ), &cpuset );
#endif
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
                            req.start_edge,
                            req.target_edge,
                            req.asf,
                            req.current_time_sec
                        );

                        res.agent_id = req.agent_id;
                        if( result )
                        {
                            res.success = true;
                            res.path_len = static_cast< uint16_t >( result->path.size() );
                            for( size_t j = 0; j < result->path.size(); ++j )
                            {
                                res.path[ j ] = result->path[ j ];
                                res.edge_etas_sec[ j ] = result->etas[ j ];
                            }
                        }
                        else
                        {
                            res.success = false;
                        }
                    } );
                }

                router_pool_.WaitForAll();
                routes_computed_.fetch_add( static_cast< uint32_t >( req_batch.size() ), std::memory_order_relaxed );
                
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
                                          { r.path.data(), r.path_len },
                                          { r.edge_etas_sec.data(), r.path_len } );

                // Reset progress if it was a forced or stuck reroute
                if( agent_pool_.route_progress_idx[ r.agent_id ] == 0 )
                {
                    agent_pool_.edge_enter_time_sec[ r.agent_id ] = static_cast< uint32_t >( current_sim_time_ );
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
