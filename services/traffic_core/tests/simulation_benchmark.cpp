#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <thread>
#include <atomic>
#include <future>
#include <filesystem>
#include <fstream>

#include "common/net/inproc_transport.hpp"
#include "common/net/typed_endpoint.hpp"
#include "common/net/messages.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/route_arena.hpp"
#include "data_provider/kinematics_system.hpp"
#include "data_provider/scenario_generator.hpp"
#include "decision_engine/mpr_engine.hpp"
#include "router/control/router_manager.hpp"

using namespace traffic::common::net;
using namespace traffic::data_provider;
using namespace traffic::decision_engine;
using namespace traffic::router::control;

/**
 * @brief Creates a simple circular topological graph for benchmarking purposes.
 * Edges form a single large loop: 0->1->2->...->(N-1)->0.
 */
void CreateFakeGraph( const std::string & data_dir, uint32_t num_nodes )
{
    namespace fs = std::filesystem;
    fs::create_directories( data_dir );

    // 1. Generate CSR Graph (csr.bin)
    // Structure: num_nodes (4b), num_edges (4b), row_ptr (4b*N+1), col_ind (4b*E), weights (4b*E)
    std::ofstream csr_file( fs::path( data_dir ) / "csr.bin", std::ios::binary );
    
    uint32_t num_edges = num_nodes;
    csr_file.write( reinterpret_cast< const char * >( &num_nodes ), sizeof( num_nodes ) );
    csr_file.write( reinterpret_cast< const char * >( &num_edges ), sizeof( num_edges ) );

    std::vector< uint32_t > row_ptr( num_nodes + 1 );
    for( uint32_t i = 0; i <= num_nodes; ++i )
    {
        row_ptr[ i ] = i;
    }
    csr_file.write( reinterpret_cast< const char * >( row_ptr.data() ), row_ptr.size() * sizeof( uint32_t ) );

    std::vector< uint32_t > col_ind( num_edges );
    for( uint32_t i = 0; i < num_edges; ++i )
    {
        col_ind[ i ] = ( i + 1 ) % num_nodes;
    }
    csr_file.write( reinterpret_cast< const char * >( col_ind.data() ), col_ind.size() * sizeof( uint32_t ) );

    std::vector< uint32_t > weights( num_edges, 100 ); // 100ms base weight
    csr_file.write( reinterpret_cast< const char * >( weights.data() ), weights.size() * sizeof( uint32_t ) );
    csr_file.close();

    // 2. Generate Geometry (geometry_flat.bin)
    // Structure: num_edges (4b), total_points (4b), offsets (4b*E+1), points (8b*P), lens (4b*P)
    std::ofstream geom_file( fs::path( data_dir ) / "geometry_flat.bin", std::ios::binary );
    uint32_t total_points = num_edges * 2;
    geom_file.write( reinterpret_cast< const char * >( &num_edges ), sizeof( num_edges ) );
    geom_file.write( reinterpret_cast< const char * >( &total_points ), sizeof( total_points ) );

    std::vector< uint32_t > offsets( num_edges + 1 );
    for( uint32_t i = 0; i <= num_edges; ++i )
    {
        offsets[ i ] = i * 2;
    }
    geom_file.write( reinterpret_cast< const char * >( offsets.data() ), offsets.size() * sizeof( uint32_t ) );

    struct Point { float x, y; };
    std::vector< Point > points( total_points );
    std::vector< float > lens( total_points );
    for( uint32_t i = 0; i < num_edges; ++i )
    {
        points[ i * 2 ] = { 0.0f, 0.0f };
        points[ i * 2 + 1 ] = { 0.0f, 100.0f }; // 100m edge
        lens[ i * 2 ] = 0.0f;
        lens[ i * 2 + 1 ] = 100.0f;
    }
    geom_file.write( reinterpret_cast< const char * >( points.data() ), points.size() * sizeof( Point ) );
    geom_file.write( reinterpret_cast< const char * >( lens.data() ), lens.size() * sizeof( float ) );
    geom_file.close();
}

int main( int argc, char ** argv )
{
    // --- CLI Argument Parsing ---
    uint32_t num_agents = 100000;
    uint16_t asf = 1;
    float accel = 1.0f;
    uint32_t duration_sim_sec = 600;

    for( int i = 1; i < argc; ++i )
    {
        std::string arg = argv[ i ];
        if( arg == "--agents" && i + 1 < argc ) num_agents = std::stoul( argv[ ++i ] );
        else if( arg == "--asf" && i + 1 < argc ) asf = static_cast< uint16_t >( std::stoul( argv[ ++i ] ) );
        else if( arg == "--accel" && i + 1 < argc ) accel = std::stof( argv[ ++i ] );
        else if( arg == "--duration" && i + 1 < argc ) duration_sim_sec = std::stoul( argv[ ++i ] );
    }

    std::cout << "=== Traffic Core Simulation Engine Benchmark ===" << std::endl;
    std::cout << " Agents:   " << num_agents << std::endl;
    std::cout << " ASF:      " << asf << std::endl;
    std::cout << " Accel:    " << accel << "x" << std::endl;
    std::cout << " Duration: " << duration_sim_sec << "s (Simulation time)" << std::endl;
    std::cout << "================================================" << std::endl;

    // --- Setup Data & Graphs ---
    const std::string tmp_dir = "./tmp_bench_data";
    uint32_t num_nodes = 10000;
    CreateFakeGraph( tmp_dir, num_nodes );

    RouterManager router_manager;
    auto graph_status = router_manager.LoadGraphs( tmp_dir );
    if( !graph_status )
    {
        std::cerr << "Failed to load generated graphs: " << graph_status.error() << std::endl;
        return 1;
    }

    // --- System Initialization ---
    auto mpr_transport = std::make_unique< InProcTransport >();
    auto router_transport = std::make_unique< InProcTransport >();
    mpr_transport->SetRemote( router_transport.get() );
    router_transport->SetRemote( mpr_transport.get() );

    TypedEndpoint< RouteRequest, RouteResponse > mpr_ep( std::move( mpr_transport ) );
    TypedEndpoint< RouteResponse, RouteRequest > router_ep( std::move( router_transport ) );

    MprEngine mpr_engine( mpr_ep );
    AgentPool agent_pool;
    RouteArena route_arena;
    KinematicsSystem kin_system( agent_pool, route_arena );

    // Populating agents
    std::vector< RouteRequest > initial_requests;
    ScenarioGenerator::SpawnRandomAgents( agent_pool, num_agents, num_nodes, asf, initial_requests );

    // Ensure inv_edge_length_m is correctly set for kinematics (ScenarioGenerator doesn't know about graph)
    for( uint32_t i = 0; i < num_agents; ++i )
    {
        agent_pool.inv_edge_length_m[ i ] = 1.0f / 100.0f; // All our fake edges are 100m
    }

    // --- Router Worker Thread ---
    std::atomic< bool > keep_running{ true };
    std::atomic< size_t > routes_computed{ 0 };
    auto router_worker = std::thread( [ & ]( ) {
        std::vector< RouteRequest > req_batch;
        std::vector< RouteResponse > res_batch;
        
        while( keep_running )
        {
            if( router_ep.Receive( req_batch ) )
            {
                res_batch.clear();
                for( const auto & req : req_batch )
                {
                    // For ring graph, route is just i -> i+1 -> ... -> target
                    // but we use actual A* to simulate load.
                    auto result = router_manager.Route< false, false >( 
                        req.start_edge, req.target_edge, req.current_time_sec 
                    );

                    RouteResponse resp {};
                    resp.agent_id = req.agent_id;
                    resp.success = result.has_value();
                    if( resp.success )
                    {
                        resp.path_len = static_cast< uint16_t >( 
                            std::min< size_t >( result->path.size(), TRAFFIC_MAX_ROUTE_PATH ) 
                        );
                        for( uint16_t p = 0; p < resp.path_len; ++p )
                        {
                            resp.path[ p ] = result->path[ p ];
                            resp.edge_etas_sec[ p ] = result->etas[ p ];
                        }
                    }
                    res_batch.push_back( resp );
                    routes_computed++;
                }
                router_ep.Send( res_batch );
            }
            std::this_thread::yield();
        }
    } );

    // --- Initial Warmup (Routing all agents) ---
    std::cout << " Warmup: Computing initial " << num_agents << " routes..." << std::flush;
    mpr_ep.Send( initial_requests );
    while( routes_computed < num_agents )
    {
        std::vector< RouteResponse > warmup_resps;
        if( mpr_ep.Receive( warmup_resps ) )
        {
            for( const auto & r : warmup_resps )
            {
                if( r.success )
                {
                    route_arena.UpdateRoute( r.agent_id, 
                                             std::span{ r.path.data(), r.path_len }, 
                                             std::span{ r.edge_etas_sec.data(), r.path_len } );
                    agent_pool.route_progress_idx[ r.agent_id ] = 0;
                    agent_pool.edge_enter_time_sec[ r.agent_id ] = 0;
                }
            }
        }
        std::this_thread::sleep_for( std::chrono::milliseconds( 10 ) );
    }
    std::cout << " Done." << std::endl;

    // --- Main Simulation Loop ---
    float dt = 0.1f;
    float current_sim_time = 0.0f;
    uint32_t last_mpr_tick = 0;
    size_t total_ticks = 0;
    size_t reroutes_triggered = 0;

    auto start_wall = std::chrono::steady_clock::now();
    std::cout << " Simulation started..." << std::endl;

    while( current_sim_time < duration_sim_sec )
    {
        auto tick_start = std::chrono::steady_clock::now();

        // Physics step (10Hz)
        kin_system.AdvanceKinematics( dt );
        kin_system.ProcessTransitions( static_cast< uint32_t >( current_sim_time ) );

        // Decision logic (1Hz)
        uint32_t sim_sec = static_cast< uint32_t >( current_sim_time );
        if( sim_sec > last_mpr_tick )
        {
            size_t old_routes = routes_computed;
            mpr_engine.Tick( sim_sec, agent_pool, route_arena );
            reroutes_triggered += ( routes_computed - old_routes );
            last_mpr_tick = sim_sec;
        }

        // Handle incoming responses from Router and apply them to the Arena
        std::vector< RouteResponse > incoming_resps;
        if( mpr_ep.Receive( incoming_resps ) )
        {
            for( const auto & r : incoming_resps )
            {
                if( r.success )
                {
                    route_arena.UpdateRoute( r.agent_id, 
                                             std::span{ r.path.data(), r.path_len }, 
                                             std::span{ r.edge_etas_sec.data(), r.path_len } );
                }
            }
        }

        current_sim_time += dt;
        total_ticks++;

        // Speed regulation (Accel)
        auto tick_end = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast< std::chrono::microseconds >( tick_end - tick_start );
        auto target_micros = static_cast< long long >( ( dt / accel ) * 1000000.0f );

        if( elapsed.count() < target_micros )
        {
            std::this_thread::sleep_for( std::chrono::microseconds( target_micros - elapsed.count() ) );
        }
    }

    auto end_wall = std::chrono::steady_clock::now();
    auto total_wall_sec = std::chrono::duration< float >( end_wall - start_wall ).count();

    keep_running = false;
    router_worker.join();

    // --- Results ---
    std::cout << "================================================" << std::endl;
    std::cout << " Benchmark Finished." << std::endl;
    std::cout << " Wall-clock time:  " << total_wall_sec << "s" << std::endl;
    std::cout << " Avg TPS (Ticks):  " << static_cast< float >( total_ticks ) / total_wall_sec << std::endl;
    std::cout << " Simulation Speed: " << duration_sim_sec / total_wall_sec << "x real-time" << std::endl;
    std::cout << " Reroutes total:   " << reroutes_triggered << std::endl;
    std::cout << "================================================" << std::endl;

    std::filesystem::remove_all( tmp_dir );
    return 0;
}
