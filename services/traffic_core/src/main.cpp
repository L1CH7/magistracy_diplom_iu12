#include <iostream>
#include <csignal>
#include <atomic>
#include <chrono>
#include <thread>

#include "common/logger.hpp"
#include "core/traffic_engine.hpp"

using namespace traffic;

static std::atomic< bool > keep_running( true );

void signal_handler( int sig )
{
    if( sig == SIGINT || sig == SIGTERM )
    {
        keep_running = false;
        LOG_INFO( "Завершение работы по сигналу..." );
    }
}

int main( int argc, char ** argv )
{
    if( argc < 2 )
    {
        std::cerr << "Usage: " << argv[ 0 ] << " <data_dir>" << std::endl;
        return 1;
    }

    core::logging::init_logger();
    LOG_INFO( "=== Traffic Core Service starting (C++26) ===" );

    std::signal( SIGINT,  signal_handler );
    std::signal( SIGTERM, signal_handler );

    std::string data_dir = argv[ 1 ];
    
    try
    {
        core::TrafficEngine engine;
        
        LOG_INFO( "Initializing TrafficEngine with data: {}", data_dir );
        auto init_status = engine.Init( data_dir );
        if( !init_status )
        {
            LOG_FATAL( "Failed to initialize TrafficEngine: {}", init_status.error() );
            return 1;
        }

        LOG_INFO( "TrafficEngine ready. Edges: {}", engine.GetRouterManager().num_edges() );

        // Initial agent spawn (demo/default)
        // In production, agents might be loaded from a scenario file or external API
        engine.SpawnAgents( 1000, 1 ); 
        engine.Warmup();

        LOG_INFO( "Simulation started. Press Ctrl+C to stop." );

        float dt = 0.1f;
        while( keep_running )
        {
            auto start = std::chrono::steady_clock::now();
            
            engine.Step( dt );

            auto end = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast< std::chrono::milliseconds >( end - start );
            
            // Limit to 10Hz
            if( elapsed.count() < 100 )
            {
                std::this_thread::sleep_for( std::chrono::milliseconds( 100 - elapsed.count() ) );
            }
        }

        engine.Stop();
        LOG_INFO( "=== Traffic Core Service shut down cleanly ===" );
    }
    catch( const std::exception & e )
    {
        LOG_FATAL( "System Exception: {}", e.what() );
        return 1;
    }

    return 0;
}
