#include <iostream>
#include <csignal>
#include <atomic>
#include <thread>
#include <zmq.hpp>
#include <chrono>

#include "common/logger.hpp"
#include "common/net/telemetry_protocol.hpp"
#include "core/traffic_engine.hpp"
#include "core/telemetry_worker.hpp"

using namespace traffic;

static std::atomic< bool > keep_running( true );

void signal_handler( int sig )
{
    if( sig == SIGINT || sig == SIGTERM )
    {
        keep_running = false;
        LOG_INFO( "Received shutdown signal..." );
    }
}

int main( int argc, char ** argv )
{
    if( argc < 2 )
    {
        std::cerr << "Usage: " << argv[ 0 ] << " <data_dir> [command_port] [telemetry_port]" << std::endl;
        return 1;
    }

    core::logging::init_logger();
    LOG_INFO( "=== Traffic Core Daemon Starting ===" );

    std::signal( SIGINT,  signal_handler );
    std::signal( SIGTERM, signal_handler );

    std::string data_dir = argv[ 1 ];
    std::string cmd_addr = "tcp://*:5555";
    std::string pub_addr = "tcp://*:5556";
    
    if( argc >= 3 ) cmd_addr = "tcp://*:" + std::string( argv[ 2 ] );
    if( argc >= 4 ) pub_addr = "tcp://*:" + std::string( argv[ 3 ] );

    try
    {
        zmq::context_t context( 1 );
        
        // 1. Initialize Modules
        core::TrafficEngine engine;
        auto init_status = engine.Init( data_dir );
        if( !init_status )
        {
            LOG_FATAL( "Engine Init Failed: {}", init_status.error() );
            return 1;
        }

        core::TelemetryWorker telemetry( context, 1000000 ); // 1M agents buffer
        telemetry.Start( pub_addr );
        engine.SetTelemetryWorker( &telemetry );

        // 2. Command Socket (REP)
        zmq::socket_t rep_socket( context, zmq::socket_type::rep );
        rep_socket.bind( cmd_addr );
        
        LOG_INFO( "Daemon listening: CMD={} PUB={}", cmd_addr, pub_addr );

        std::thread engine_thread;
        bool engine_running = false;

        while( keep_running )
        {
            zmq::message_t request_msg;
            // Non-blocking poll or short timeout to check keep_running
            auto res = rep_socket.recv( request_msg, zmq::recv_flags::dontwait );
            if( !res )
            {
                std::this_thread::sleep_for( std::chrono::milliseconds( 10 ) );
                continue;
            }

            if( request_msg.size() < sizeof( common::net::CommandRequest ) )
            {
                common::net::CommandAck ack{ 0, static_cast<uint8_t>(engine_running) };
                rep_socket.send( zmq::message_t( &ack, sizeof( ack ) ), zmq::send_flags::none );
                continue;
            }

            auto * cmd = static_cast< const common::net::CommandRequest * >( request_msg.data() );
            common::net::CommandAck ack{ 1, 0 };

            switch( cmd->opcode )
            {
                case common::net::CommandOpcode::START:
                    if( !engine_running )
                    {
                        LOG_INFO( "Command: START agents={} accel={}", cmd->num_agents, cmd->acceleration );
                        engine.SpawnAgents( cmd->num_agents, cmd->asf );
                        engine.Warmup();
                        LOG_INFO("Engine Warmed up with {} agents", cmd->num_agents);
                        
                        float accel = cmd->acceleration;
                        engine_thread = std::thread( [ &engine, accel ]( ) {
                            engine.Run( accel );
                        } );
                        engine_running = true;
                    }
                    break;

                case common::net::CommandOpcode::STOP:
                    LOG_INFO( "Command: STOP" );
                    if( engine_running )
                    {
                        engine.Stop();
                        if( engine_thread.joinable() ) engine_thread.join();
                        engine_running = false;
                    }
                    break;

                case common::net::CommandOpcode::SET_SPEED:
                    LOG_INFO( "Command: SET_SPEED accel={}", cmd->acceleration );
                    engine.SetAcceleration( cmd->acceleration );
                    break;

                case common::net::CommandOpcode::ROUTE_ONE_OFF:
                {
                    LOG_INFO( "Command: ROUTE_ONE_OFF" );
                    if( request_msg.size() < sizeof( common::net::CommandRequest ) + sizeof( common::net::OneOffRouteHeader ) )
                    {
                         common::net::OneOffRouteResponseHeader err_header{ 0, 0, 0, 0.0f, 0.0f };
                         rep_socket.send( zmq::message_t( &err_header, sizeof( err_header ) ), zmq::send_flags::none );
                         continue;
                    }

                    auto * route_header = reinterpret_cast< const common::net::OneOffRouteHeader * >( 
                        static_cast< const uint8_t * >( request_msg.data() ) + sizeof( common::net::CommandRequest ) 
                    );
                    
                    uint32_t expected_size = sizeof( common::net::CommandRequest ) + sizeof( common::net::OneOffRouteHeader ) + 
                                            route_header->num_waypoints * sizeof( common::net::PointCoord );
                    
                    if( request_msg.size() < expected_size )
                    {
                         common::net::OneOffRouteResponseHeader err_header{ 0, 0, 0, 0.0f, 0.0f };
                         rep_socket.send( zmq::message_t( &err_header, sizeof( err_header ) ), zmq::send_flags::none );
                         continue;
                    }

                    const auto * points = reinterpret_cast< const common::net::PointCoord * >( 
                        static_cast< const uint8_t * >( request_msg.data() ) + sizeof( common::net::CommandRequest ) + sizeof( common::net::OneOffRouteHeader )
                    );

                    std::vector< std::pair< float, float > > coords;
                    coords.reserve( route_header->num_waypoints );
                    for( int i = 0; i < route_header->num_waypoints; ++i )
                    {
                        coords.emplace_back( points[ i ].lon, points[ i ].lat );
                    }

                    LOG_DEBUG( "Processing one-off route: {} waypoints", coords.size() );

                    // Use internal engine's RouterManager for simulation-aware routing (baskets etc)
                    auto & rm = engine.GetRouterManager(); 
                    auto start_calc = std::chrono::steady_clock::now();
                    auto result = rm.Route< true, false >( coords, route_header->start_time_sec );
                    auto end_calc = std::chrono::steady_clock::now();
                    float calc_ms = std::chrono::duration<float, std::milli>(end_calc - start_calc).count();

                    if( result )
                    {
                        LOG_INFO( "Route found: {} edges, total_time={}s", result->path.size(), result->total_weight );

                        common::net::OneOffRouteResponseHeader res_header;
                        res_header.success = 1;
                        res_header.num_edges = static_cast< uint16_t >( result->path.size() );
                        res_header.total_distance_m = 0.0f; // Could be summed from edges
                        res_header.total_time_sec = static_cast< float >( result->total_weight );
                        res_header.calc_time_ms = calc_ms;

                        std::vector< uint16_t > point_counts;
                        std::vector< common::net::PointCoord > geometry;
                        std::vector< float > etas;

                        point_counts.reserve( result->path.size() );
                        geometry.reserve( result->path.size() * 5 ); // Estimate
                        etas.reserve( result->path.size() );

                        for( size_t i = 0; i < result->path.size(); ++i )
                        {
                            auto edge_id = result->path[ i ];
                            auto geom = rm.get_geometry_store()->get_geometry( edge_id );
                            
                            point_counts.push_back( static_cast< uint16_t >( geom.points.size() ) );
                            for( const auto & pt : geom.points )
                            {
                                geometry.push_back( common::net::PointCoord{ pt.x, pt.y } );
                            }
                            etas.push_back( static_cast< float >( result->etas[ i ] ) );
                            res_header.total_distance_m += geom.accum_lens.back();
                        }
                        res_header.total_points = static_cast<uint32_t>(geometry.size());

                        // Send multi-frame response
                        rep_socket.send( zmq::message_t( &res_header, sizeof( res_header ) ), zmq::send_flags::sndmore );
                        rep_socket.send( zmq::message_t( result->path.data(), result->path.size() * sizeof( uint32_t ) ), zmq::send_flags::sndmore );
                        rep_socket.send( zmq::message_t( etas.data(), etas.size() * sizeof( float ) ), zmq::send_flags::sndmore );
                        rep_socket.send( zmq::message_t( point_counts.data(), point_counts.size() * sizeof( uint16_t ) ), zmq::send_flags::sndmore );
                        rep_socket.send( zmq::message_t( geometry.data(), geometry.size() * sizeof( common::net::PointCoord ) ), zmq::send_flags::none );
                    }
                    else
                    {
                        common::net::OneOffRouteResponseHeader err_header{ 0, 0, 0, 0.0f, 0.0f };
                        rep_socket.send( zmq::message_t( &err_header, sizeof( err_header ) ), zmq::send_flags::none );
                    }
                    continue; // REP/REQ finished
                }

                default:
                    ack.success = 0;
                    break;
            }

            ack.engine_state = engine_running ? 1 : 0;
            rep_socket.send( zmq::message_t( &ack, sizeof( ack ) ), zmq::send_flags::none );
        }

        if( engine_running )
        {
            engine.Stop();
            if( engine_thread.joinable() ) engine_thread.join();
        }
        
        telemetry.Stop();
        LOG_INFO( "Traffic Core Daemon stopped cleanly." );
    }
    catch( const std::exception & e )
    {
        LOG_FATAL( "Daemon Exception: {}", e.what() );
        return 1;
    }

    return 0;
}
