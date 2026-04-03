#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <thread>
#include <atomic>
#include <future>
#include <filesystem>
#include <fstream>
#include <random>
#include <csignal>
#include <sstream>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

#include "core/traffic_engine.hpp"
#include "data_provider/scenario_generator.hpp"

using namespace traffic::common::net;
using namespace traffic::data_provider;
using namespace traffic::decision_engine;
using namespace traffic::router::control;

static std::atomic< bool > g_signal_received{ false };

void SignalHandler( int )
{
    g_signal_received.store( true );
}

int main( int argc, char ** argv )
{
    // --- CLI Argument Parsing ---
    uint32_t num_agents = 100000;
    uint16_t asf = 1;
    float accel = 1.0f;
    uint32_t duration_sim_sec = 600;
    std::string data_path = "/app/data";
    uint32_t affinity_sim = 1;
    bool use_affinity = true;
    uint32_t chaos_percent = 0;

    for( int i = 1; i < argc; ++i )
    {
        std::string arg = argv[ i ];
        if( arg == "--agents" && i + 1 < argc ) num_agents = std::stoul( argv[ ++i ] );
        else if( arg == "--asf" && i + 1 < argc ) asf = static_cast< uint16_t >( std::stoul( argv[ ++i ] ) );
        else if( arg == "--accel" && i + 1 < argc ) accel = std::stof( argv[ ++i ] );
        else if( arg == "--duration" && i + 1 < argc ) duration_sim_sec = std::stoul( argv[ ++i ] );
        else if( arg == "--affinity_sim" && i + 1 < argc ) affinity_sim = std::stoul( argv[ ++i ] );
        else if( arg == "--use_affinity" && i + 1 < argc ) use_affinity = ( std::stoul( argv[ ++i ] ) != 0 );
        else if( arg == "--chaos" && i + 1 < argc ) chaos_percent = std::stoul( argv[ ++i ] );
        else if( arg == "--data" && i + 1 < argc ) data_path = argv[ ++i ];
    }

    // --- Thread Affinity Binding ---
#ifdef __linux__
    cpu_set_t cpuset;
    CPU_ZERO( &cpuset );
    CPU_SET( affinity_sim, &cpuset );
    int rc = pthread_setaffinity_np( pthread_self(), sizeof( cpu_set_t ), &cpuset );
    if( rc != 0 )
    {
        std::cerr << "Warning: Failed to set thread affinity to core " << affinity_sim << std::endl;
    }
    else
    {
        std::cout << " [Main] Bound to CPU core: " << affinity_sim << std::endl;
    }
#endif

    // --- Signal Handling Registration ---
    std::signal( SIGINT, SignalHandler );
    std::signal( SIGTERM, SignalHandler );

    std::cout << "=== Traffic Core Simulation Engine Benchmark ===" << std::endl;
    std::cout << " Agents:   " << num_agents << std::endl;
    std::cout << " ASF:      " << asf << std::endl;
    std::cout << " Accel:    " << accel << "x" << std::endl;
    std::cout << " Duration: " << duration_sim_sec << "s (Simulation time)" << std::endl;
    std::cout << " Chaos:    " << chaos_percent << "%" << std::endl;
    std::cout << " Data:     " << data_path << std::endl;
    std::cout << "================================================" << std::endl;

    // --- Traffic Engine Initialization ---
    std::string cores_str = TRAFFIC_ROUTER_CORES;
    std::vector< int > router_cores;
    std::stringstream ss_cores( cores_str );
    std::string item;
    while( std::getline( ss_cores, item, ',' ) )
    {
        if( !item.empty() ) router_cores.push_back( std::stoi( item ) );
    }

    traffic::core::TrafficEngine engine( router_cores );
    
    auto init_start_wall = std::chrono::steady_clock::now();
    std::cout << " [1/3] Loading Graphs from: " << data_path << "..." << std::flush;
    auto init_status = engine.Init( data_path );
    if( !init_status )
    {
        std::cerr << "\nFailed to initialize engine: " << init_status.error() << std::endl;
        return 1;
    }
    std::cout << " Done." << std::endl;

    std::cout << " [2/3] num_edges=" << engine.GetRouterManager().num_edges() << std::endl;

    // Populating agents
    engine.SpawnAgents( num_agents, asf );

    auto init_end_wall = std::chrono::steady_clock::now();
    float init_sec = std::chrono::duration< float >( init_end_wall - init_start_wall ).count();
    std::cout << " Init Phase Done in " << init_sec << "s." << std::endl;

    // --- Initial Warmup ---
    std::cout << " Warmup: Computing initial " << num_agents << " routes..." << std::flush;
    auto warmup_start_wall = std::chrono::steady_clock::now();
    engine.Warmup();
    auto warmup_end_wall = std::chrono::steady_clock::now();
    float warmup_sec = std::chrono::duration< float >( warmup_end_wall - warmup_start_wall ).count();
    std::cout << " Done in " << warmup_sec << "s." << std::endl;

    // --- Main Simulation Loop ---
    float dt = 0.1f;
    size_t total_ticks = 0;
    size_t total_edge_transitions = 0;
    size_t reroutes_triggered = 0;
    size_t last_computed_routes = engine.GetRoutesComputed();

    // PRNG for Chaos injection
    static std::mt19937 chaos_gen{ 42 }; // Use fixed seed for reproducibility
    std::uniform_int_distribution< uint32_t > prob_dist( 0, 99 );
    std::uniform_int_distribution< uint32_t > agent_dist( 0, num_agents - 1 );

    auto start_wall = std::chrono::steady_clock::now();
    std::cout << " Simulation started... (Press Ctrl+C to stop early)" << std::endl;

    while( engine.GetCurrentSimTime() < duration_sim_sec && !g_signal_received.load() )
    {
        auto tick_start = std::chrono::steady_clock::now();

        // Chaos Injection (Task 5)
        if( chaos_percent > 0 && total_ticks % 10 == 0 )
        {
            uint32_t agents_to_stop = ( num_agents * chaos_percent ) / 100;
            for( uint32_t i = 0; i < agents_to_stop; ++i )
            {
                uint32_t random_id = agent_dist( chaos_gen );
                auto & agent_pool = engine.GetAgentPool();
                if( agent_pool.is_active[ random_id ] )
                {
                    agent_pool.velocity_mps[ random_id ] = 0.0f;
                }
            }
        }

        engine.Step( dt );
        
        size_t current_computed = engine.GetRoutesComputed();
        if( current_computed > last_computed_routes )
        {
            reroutes_triggered += ( current_computed - last_computed_routes );
            last_computed_routes = current_computed;
        }

        total_edge_transitions += engine.GetAgentPool().transition_queue.size();
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
    
    // Final check for remaining responses
    std::this_thread::sleep_for( std::chrono::milliseconds( 100 ) );
    engine.Stop();

    // --- Results ---
    size_t final_routes = engine.GetRoutesComputed();
    std::cout << "================================================" << std::endl;
    std::cout << " Benchmark Finished." << std::endl;
    std::cout << " Init time:        " << init_sec << "s" << std::endl;
    std::cout << " Warmup time:      " << warmup_sec << "s" << std::endl;
    std::cout << " Sim loop time:    " << total_wall_sec << "s" << std::endl;
    std::cout << " Avg TPS (Ticks):  " << static_cast< float >( total_ticks ) / total_wall_sec << std::endl;
    std::cout << " Simulation Speed: " << ( duration_sim_sec / total_wall_sec ) << "x real-time" << std::endl;
    std::cout << " Reroutes total:   " << final_routes << " (Triggered during sim: " << reroutes_triggered << ")" << std::endl;
    std::cout << " Routes Succeeded: " << engine.GetTotalSuccessfulRoutes() << std::endl;
    std::cout << " Routes Failed:    " << engine.GetTotalFailedRoutes() << std::endl;
    std::cout << " Edges Crossed:    " << total_edge_transitions << std::endl;
    std::cout << "================================================" << std::endl;

    return 0;
}
