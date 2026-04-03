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

    // Pre-build per-edge occupancy and lengths for PhysicsContext (avoids geometry_store lookup per tick)
    size_t n_edges = static_cast< size_t >( router_manager_.num_edges() );
    live_edge_volumes_.assign( n_edges, 0 );
    max_live_volumes_.assign( n_edges, 0 );
    edge_lengths_cache_.resize( n_edges );
    for( size_t i = 0; i < n_edges; ++i )
    {
        edge_lengths_cache_[ i ] = router_manager_.get_edge_length( static_cast< traffic::EdgeID >( i ) );
    }

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

    // Task 1: Fix physics initialization
    // - [x] Update `traffic_engine.cpp`
    // - [x] Initialize `max_live_volumes_` in `Init()`
    // - [x] Pass `max_live_volumes_.data()` in `MakePhysicsContext()`
    // - [x] Update peak volumes in `HandleResponses()` for initial activation
    for( uint32_t i = 0; i < num_agents; ++i )
    {
        float length = router_manager_.get_edge_length( agent_pool_.current_edge[ i ] );
        agent_pool_.inv_edge_length_m[ i ] = ( length > 0.001f ) ? ( 1.0f / length ) : 1.0f;
    }
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

    // Phase 1: Locomotion - BPR speed is set at edge entry in ProcessTransitions (O(transitions))
    kin_system_.AdvanceKinematics( dt );
    total_completed_routes_ += kin_system_.ProcessTransitions(
        MakePhysicsContext( static_cast< uint32_t >( current_sim_time_ ) )
    );

    // Phase 2: Decision Making (MPR - Mesoscopic Path Rerouting)
    uint32_t sim_sec = static_cast< uint32_t >( current_sim_time_ );
    if( sim_sec > last_mpr_tick_sim_sec_ )
    {
        mpr_requests_buffer_.clear();
        mpr_engine_->Tick( sim_sec, agent_pool_, route_arena_, mpr_requests_buffer_ );

        if( !mpr_requests_buffer_.empty() )
        {
            auto vol_mgr = router_manager_.get_volume_manager();
            if( vol_mgr )
            {
                for( const auto & req : mpr_requests_buffer_ )
                {
                    auto path = route_arena_.GetRoute( req.agent_id );
                    auto etas = route_arena_.GetEtas( req.agent_id );
                    if( !path.empty() ) vol_mgr->unbook_route( path, etas, 1 );
                }
            }
            mpr_ep_->Send( mpr_requests_buffer_ );
        }
        last_mpr_tick_sim_sec_ = sim_sec;
    }

    float old_sim_time = current_sim_time_;
    current_sim_time_ += dt;

    // Сдвигаем окно времени в корзинках, чтобы зачистить прошедший трафик
    auto vol_mgr = router_manager_.get_volume_manager();
    if( vol_mgr )
    {
        vol_mgr->advance_time( static_cast< uint32_t >( old_sim_time ),
                               static_cast< uint32_t >( current_sim_time_ ) );
    }

    // Phase 2.5: Agent Recirculation (Task 2 & 3: Rate Limiter)
    static std::mt19937 rec_gen{ std::random_device{}( ) };
    std::uniform_int_distribution< uint32_t > edge_dist( 0, static_cast< uint32_t >( router_manager_.num_edges() ) - 1 );

    uint32_t respawn_quota = 1000; // Task 3: Limit respawns per tick
    mpr_requests_buffer_.clear(); // Reuse buffer for respawn requests
    for( uint32_t i = 0; i < num_agents_; ++i )
    {
        if( agent_pool_.is_active[ i ] == 0 && respawn_quota > 0 )
        {
            respawn_quota--;
            uint32_t start_edge = edge_dist( rec_gen );
            uint32_t target_edge = edge_dist( rec_gen );
            while( target_edge == start_edge ) target_edge = edge_dist( rec_gen );

            agent_pool_.current_edge[ i ] = start_edge;
            agent_pool_.target_edge[ i ] = target_edge;
            agent_pool_.pos_meters[ i ] = 0.0f;
            
            // СТОП! Машина не должна двигаться, пока нет маршрута (Task: Fix Respawn Loop)
            agent_pool_.velocity_mps[ i ] = 0.0f; 
            
            float length = edge_lengths_cache_.empty()
                               ? router_manager_.get_edge_length( start_edge )
                               : edge_lengths_cache_[ start_edge ];
            agent_pool_.inv_edge_length_m[ i ] = ( length > 0.001f ) ? ( 1.0f / length ) : 1.0f;
            
            // 2 = Состояние ожидания маршрута. Физика её не тронет.
            agent_pool_.is_active[ i ] = 2; 

            mpr_requests_buffer_.push_back( {
                .agent_id = i,
                .start_edge = start_edge,
                .target_edge = target_edge,
                .asf = 50, // Default ASF for respawn
                .current_time_sec = static_cast< uint32_t >( current_sim_time_ )
            } );
        }
    }
    if( !mpr_requests_buffer_.empty() )
    {
        auto vol_mgr = router_manager_.get_volume_manager();
        if( vol_mgr )
        {
            for( const auto & req : mpr_requests_buffer_ )
            {
                auto path = route_arena_.GetRoute( req.agent_id );
                auto etas = route_arena_.GetEtas( req.agent_id );
                if( !path.empty() ) vol_mgr->unbook_route( path, etas, 1 );
            }
        }
        mpr_ep_->Send( mpr_requests_buffer_ );
    }

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
    router_pool_.Stop();
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
        uint32_t empty_polls = 0;

        while( keep_running_ )
        {
            if( router_ep_->Receive( req_batch ) )
            {
                res_batch.resize( req_batch.size() );
                for( size_t i = 0; i < req_batch.size(); ++i )
                {
                    router_pool_.Enqueue( [ this, &req = req_batch[ i ], &res = res_batch[ i ] ]( ) {
                        auto result = router_manager_.Route< true, false >( // Force vector overload to prevent implicit float cast
                            std::vector< traffic::NodeID >{ req.start_edge, req.target_edge },
                            req.current_time_sec
                        );

                        res.agent_id = req.agent_id;
                        if( result )
                        {
                            res.success = true;
                            res.path_len = static_cast< uint16_t >( std::min<size_t>(result->path.size(), traffic::common::net::MAX_ROUTE_PATH) );
                            for( size_t j = 0; j < res.path_len; ++j )
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
                empty_polls = 0;
            }
            else
            {
                // Не жжем ядро, если запросов нет (Task: Optimization)
                if (empty_polls < 4000) {
                    _mm_pause();
                    empty_polls++;
                } else {
                    std::this_thread::sleep_for(std::chrono::milliseconds(1));
                }
            }
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
                total_successful_routes_++;
                route_arena_.UpdateRoute( r.agent_id,
                                          { r.path.data(), r.path_len },
                                          { r.edge_etas_sec.data(), r.path_len } );

                auto vol_mgr = router_manager_.get_volume_manager();
                if( vol_mgr )
                {
                    vol_mgr->book_route( route_arena_.GetRoute( r.agent_id ),
                                         route_arena_.GetEtas( r.agent_id ),
                                         1 /* weight */ );
                }

                // Task 3: Unconditional reset to prevent race conditions
                agent_pool_.route_progress_idx[ r.agent_id ] = 0;
                agent_pool_.edge_enter_time_sec[ r.agent_id ] = static_cast< uint32_t >( current_sim_time_ );

                // Маршрут получен. Обновляем геометрию начальный ребра и скорость по BPR.
                traffic::EdgeID first_edge = route_arena_.GetRoute( r.agent_id )[ 0 ];
                float first_len = edge_lengths_cache_.empty()
                                      ? router_manager_.get_edge_length( first_edge )
                                      : edge_lengths_cache_[ first_edge ];
                agent_pool_.inv_edge_length_m[ r.agent_id ] =
                    ( first_len > 0.001f ) ? ( 1.0f / first_len ) : 1.0f;

                // Увеличиваем счетчик реальной загрузки только если агент только что активировался (чтобы не дублировать при MPR-рероутах)
                if( agent_pool_.is_active[ r.agent_id ] != 1 )
                {
                    live_edge_volumes_[ first_edge ]++;
                    if( live_edge_volumes_[ first_edge ] > max_live_volumes_[ first_edge ] )
                        max_live_volumes_[ first_edge ] = live_edge_volumes_[ first_edge ];
                }

                agent_pool_.is_active[ r.agent_id ] = 1;
                agent_pool_.velocity_mps[ r.agent_id ] = data_provider::ComputeEdgeEntrySpeed(
                    first_edge,
                    MakePhysicsContext( static_cast< uint32_t >( current_sim_time_ ) ),
                    first_len
                );
            }
            else
            {
                total_failed_routes_++;
                // Маршрут не найден. Агент остается мертвым (или становится им) и ждет квоту на респавн
                agent_pool_.is_active[ r.agent_id ] = 0;
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

data_provider::PhysicsContext TrafficEngine::MakePhysicsContext( uint32_t time_sec ) const noexcept
{
    data_provider::PhysicsContext ctx;
    ctx.current_time_sec = time_sec;
    ctx.edge_lengths_m = edge_lengths_cache_.empty() ? nullptr : edge_lengths_cache_.data();
    ctx.live_volumes   = const_cast< uint32_t * >( live_edge_volumes_.data() );
    ctx.max_volumes    = const_cast< uint32_t * >( max_live_volumes_.data() );
    ctx.k_magic        = router_manager_.get_kmagic_ptr();

    // Expose the static CSR weights (free-flow travel time per edge in seconds)
    const auto & view = router_manager_.get_view();
    ctx.static_weights = view.static_weights;

    return ctx;
}

} // namespace traffic::core
