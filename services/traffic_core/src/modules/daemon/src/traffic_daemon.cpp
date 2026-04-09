#include <iostream>
#include <csignal>
#include <atomic>
#include <thread>
#include <zmq.hpp>
#include <chrono>

#include <sstream>
#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

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

    // 1. Читаем Router Cores из ENV
    std::string cores_str = "2,8,3,9,4,10,5,11";
    if (const char* env_cores = std::getenv("TRAFFIC_ROUTER_CORES")) {
        cores_str = env_cores;
    }
    
    std::vector<int> router_cores;
    std::stringstream ss_cores(cores_str);
    std::string item;
    while (std::getline(ss_cores, item, ',')) {
        if (!item.empty()) router_cores.push_back(std::stoi(item));
    }

    // 2. Читаем Sim Affinity из ENV
    int sim_affinity = 1;
    if (const char* env_sim = std::getenv("TRAFFIC_SIM_AFFINITY")) {
        sim_affinity = std::stoi(env_sim);
    }

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
        
        // 2. Initialize Engine
        core::TrafficEngine engine(router_cores);
        auto init_status = engine.Init( data_dir );
        if( !init_status )
        {
            LOG_FATAL( "Engine Init Failed: {}", init_status.error() );
            return 1;
        }

        core::TelemetryWorker telemetry( context, 1000000 ); // 1M agents buffer
        telemetry.Start( pub_addr );
        engine.SetTelemetryWorker( &telemetry );

        // 3. Command Socket (REP)
        zmq::socket_t rep_socket( context, zmq::socket_type::rep );
        rep_socket.bind( cmd_addr );
        
        // Настройка таймаута сокета вместо dontwait-спиннинга
        int timeout_ms = 500;
        rep_socket.set(zmq::sockopt::rcvtimeo, timeout_ms);
        
        LOG_INFO( "Daemon listening: CMD={} PUB={} SIM_CPU={}", 
                  cmd_addr, pub_addr, sim_affinity );

        std::thread engine_thread;
        std::atomic<bool> engine_running{false};

        while( keep_running )
        {
            zmq::message_t request_msg;
            auto res = rep_socket.recv( request_msg, zmq::recv_flags::none );
            
            if( !res ) {
                continue; // Таймаут 500мс истек, проверяем keep_running и крутим снова
            }

            if( request_msg.size() < sizeof( common::net::CommandRequest ) )
            {
                common::net::CommandAck ack{ 0, static_cast<uint8_t>(engine_running) };
                rep_socket.send( zmq::message_t( &ack, sizeof( ack ) ), zmq::send_flags::none );
                continue;
            }

            auto * cmd = static_cast< const common::net::CommandRequest * >( request_msg.data() );
            common::net::CommandAck ack{ 1, 0 };

            switch( static_cast<common::net::CommandOpcode>(cmd->opcode) )
            {
                case common::net::CommandOpcode::STOP:
                    LOG_INFO("Command: STOP");
                    engine_running = false;
                    if (engine_thread.joinable()) {
                        engine_thread.join();
                        LOG_INFO("Engine thread joined successfully.");
                    }
                    engine.ResetState();
                    break;

                case common::net::CommandOpcode::START:
                    if (engine_running) {
                        LOG_WARN("START received while engine is running. Forcing stop...");
                        engine_running = false;
                        if (engine_thread.joinable()) engine_thread.join();
                        engine.ResetState();
                    }

                    LOG_INFO("Command: START agents={} asf={} accel={} fps={} chaos={} respawn={}", 
                             cmd->num_agents, cmd->asf, cmd->acceleration, cmd->telemetry_fps, 
                             cmd->chaos_factor, cmd->respawn_enabled);
                    
                    engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor);
                    engine.SetRespawn(cmd->respawn_enabled > 0);
                    engine.PauseRouter(false);

                    // If we already have agents, skip spawning to allow resuming warmup
                    if (engine.GetActiveAgents() != cmd->num_agents || engine.GetActiveAgents() == 0) {
                        engine.SpawnAgents(cmd->num_agents, cmd->asf);
                    }

                    engine_running = true;
                    engine_thread = std::thread([&engine, &engine_running, sim_affinity, num_agents = cmd->num_agents]() {
#ifdef __linux__
                        cpu_set_t cpuset_sim;
                        CPU_ZERO(&cpuset_sim);
                        CPU_SET(sim_affinity, &cpuset_sim);
                        pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset_sim);
#endif
                        uint32_t active = engine.GetActiveAgents();
                        if (engine.GetRoutesComputed() < active) {
                            LOG_INFO("Engine WARMING UP...");
                            engine.Warmup(&engine_running);
                            if (!engine_running) {
                                LOG_INFO("Engine Warmup aborted");
                                return;
                            }
                            LOG_INFO("Engine Warmed up. Active agents: {}", engine.GetActiveAgents());
                        } else {
                            LOG_INFO("Engine already warmed up with {} agents, resuming...", active);
                        }

                        float dt = 5.0f;
                        while (engine_running) {
                            auto tick_start = std::chrono::steady_clock::now();
                            
                            float accel = engine.GetCurrentAcceleration();
                            if (accel > 0.0f) {
                                engine.Step(dt);
                                engine.UpdateTelemetry();

                                auto tick_end = std::chrono::steady_clock::now();
                                auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(tick_end - tick_start);
                                auto target_micros = static_cast<long long>((dt / accel) * 1000000.0f);
                                if (elapsed.count() < target_micros) {
                                    std::this_thread::sleep_for(std::chrono::microseconds(target_micros - elapsed.count()));
                                }
                            } else {
                                // Paused
                                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                            }
                        }
                    });
                    break;
                case common::net::CommandOpcode::PAUSE:
                    LOG_INFO("Command: PAUSE");
                    engine_running = false;
                    engine.PauseRouter(true);
                    if (engine_thread.joinable()) {
                        engine_thread.join();
                        LOG_INFO("Engine thread joined successfully. Simulation paused.");
                    }
                    break;
                
                case common::net::CommandOpcode::RESUME:
                    if (engine_running) {
                        LOG_WARN("RESUME received while engine is running. Ignoring...");
                        break;
                    }

                    LOG_INFO("Command: RESUME accel={} fps={} chaos={} respawn={}", 
                             cmd->acceleration, cmd->telemetry_fps, 
                             cmd->chaos_factor, cmd->respawn_enabled);
                    
                    engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor);
                    engine.SetRespawn(cmd->respawn_enabled > 0);
                    engine.PauseRouter(false);

                    engine_running = true;
                    engine_thread = std::thread([&engine, &engine_running, sim_affinity]() {
#ifdef __linux__
                        cpu_set_t cpuset_sim;
                        CPU_ZERO(&cpuset_sim);
                        CPU_SET(sim_affinity, &cpuset_sim);
                        pthread_setaffinity_np(pthread_self(), sizeof(cpu_set_t), &cpuset_sim);
#endif
                        uint32_t active = engine.GetActiveAgents();
                        if (engine.GetRoutesComputed() < active) {
                            LOG_INFO("Engine WARMING UP (Resumed)...");
                            engine.Warmup(&engine_running);
                            if (!engine_running) {
                                LOG_INFO("Engine Warmup aborted");
                                return;
                            }
                            LOG_INFO("Engine Warmed up. Active agents: {}", active);
                        } else {
                            LOG_INFO("Engine resuming with {} agents", active);
                        }

                        auto last_time = std::chrono::steady_clock::now();
                        while (engine_running) {
                            auto now = std::chrono::steady_clock::now();
                            std::chrono::duration<float> dt_duration = now - last_time;
                            float dt = dt_duration.count();
                            last_time = now;

                            float accel = engine.GetCurrentAcceleration();
                            if (accel > 0.0f) {
                                engine.Step(dt);
                                engine.UpdateTelemetry();
                            } else {
                                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                            }
                            
                            float target_fps = engine.GetCurrentFps();
                            if (target_fps > 0.0f) {
                                auto elapsed = std::chrono::steady_clock::now() - now;
                                float target_micros = (1.0f / target_fps) * 1000000.0f;
                                if (elapsed.count() < target_micros) {
                                    std::this_thread::sleep_for(std::chrono::microseconds(static_cast<long>(target_micros - elapsed.count())));
                                }
                            }
                        }
                    });
                    break;

                case common::net::CommandOpcode::SET_SPEED:
                    LOG_INFO("Command: SET_SPEED accel={} fps={} chaos={}", 
                             cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor);
                    engine.ApplySettings(cmd->acceleration, cmd->telemetry_fps, cmd->chaos_factor);
                    break;

                case common::net::CommandOpcode::STEP:
                    LOG_INFO("Command: STEP");
                    engine.Step(0.1f);
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

            if (engine_running) ack.engine_state = 1;
            else if (engine.GetActiveAgents() > 0) ack.engine_state = 2; // PAUSED
            else ack.engine_state = 0; // IDLE
            rep_socket.send( zmq::message_t( &ack, sizeof( ack ) ), zmq::send_flags::none );
        }

        engine_running = false;
        engine.Stop();
        if( engine_thread.joinable() ) engine_thread.join();
        
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
