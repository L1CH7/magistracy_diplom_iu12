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
    traffic::core::TrafficEngine engine;
    
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

    // --- Initial Warmup ---
    std::cout << " Warmup: Computing initial " << num_agents << " routes..." << std::flush;
    engine.Warmup();
    std::cout << " Done." << std::endl;
    std::cout << " Done." << std::endl;

    // --- Main Simulation Loop ---
    float dt = 0.1f;
    float current_sim_time = 0.0f;
    uint32_t last_mpr_tick = 0;
    size_t total_ticks = 0;
    size_t reroutes_triggered = 0;
    size_t total_edge_transitions = 0;

    // PRNG for Chaos injection
    static std::mt19937 chaos_gen{ std::random_device{}( ) };
    std::uniform_int_distribution< uint32_t > prob_dist( 0, 99 );
    std::uniform_int_distribution< uint32_t > agent_dist( 0, num_agents - 1 );

    auto start_wall = std::chrono::steady_clock::now();
    std::cout << " Simulation started... (Press Ctrl+C to stop early)" << std::endl;

    while( engine.GetCurrentSimTime() < duration_sim_sec && !g_signal_received.load() )
    {
        auto tick_start = std::chrono::steady_clock::now();

        // Chaos Injection: останавливаем заданный процент машин в КАЖДУЮ секунду
        if( chaos_percent > 0 )
        {
            // Чтобы не перегружать каждый тик (dt=0.1), будем устраивать хаос раз в 1 секунду (10 тиков)
            if (total_ticks % 10 == 0) 
            {
                uint32_t agents_to_stop = (num_agents * chaos_percent) / 100;
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
        }

        size_t old_routes = engine.GetRoutesComputed();
        engine.Step( dt );
        
        reroutes_triggered += ( engine.GetRoutesComputed() - old_routes );
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
    engine.Stop();

    // --- Results ---
    std::cout << "================================================" << std::endl;
    std::cout << " Benchmark Finished." << std::endl;
    std::cout << " Wall-clock time:  " << total_wall_sec << "s" << std::endl;
    std::cout << " Avg TPS (Ticks):  " << static_cast< float >( total_ticks ) / total_wall_sec << std::endl;
    std::cout << " Simulation Speed: " << duration_sim_sec / total_wall_sec << "x real-time" << std::endl;
    std::cout << " Reroutes total:   " << reroutes_triggered << std::endl;
    std::cout << " Edges Crossed:    " << total_edge_transitions << std::endl;
    std::cout << "================================================" << std::endl;

    return 0;
}
