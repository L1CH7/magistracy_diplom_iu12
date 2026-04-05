#include "core/telemetry_worker.hpp"
#include <chrono>
#include <thread>
#include <iostream>
#include <pthread.h>

namespace traffic::core
{

TelemetryWorker::TelemetryWorker( zmq::context_t & context, uint32_t max_agents )
    : pub_socket_( context, zmq::socket_type::pub )
{
    // Pre-allocate buffers to avoid heap fragmentation and jitter in hot loop
    buffers_[ 0 ].reserve( max_agents );
    buffers_[ 1 ].reserve( max_agents );
}

TelemetryWorker::~TelemetryWorker()
{
    Stop();
}

void TelemetryWorker::Start( const std::string & bind_addr )
{
    pub_socket_.bind( bind_addr );
    keep_running_ = true;
    worker_thread_ = std::thread( &TelemetryWorker::WorkerLoop, this );
}

void TelemetryWorker::Stop()
{
    keep_running_ = false;
    if( worker_thread_.joinable() )
    {
        worker_thread_.join();
    }
}

void TelemetryWorker::Publish( const common::net::TelemetryHeader & header )
{
    current_header_ = header;
    // Swap buffer logically and mark as ready to send
    active_idx_.store( 1 - active_idx_.load( std::memory_order_relaxed ), std::memory_order_release );
    data_ready_.store( true, std::memory_order_release );
}

void TelemetryWorker::SendEvent( common::net::EventType type, uint32_t agent_id, std::span< const traffic::EdgeID > path )
{
    std::lock_guard< std::mutex > lock( event_mutex_ );

    common::net::EventHeader header;
    header.type = type;
    header.agent_id = agent_id;
    header.payload_len = static_cast< uint16_t >( path.size() );

    // ZMQ multi-frame: Frame 1 (Header), Frame 2 (Path data)
    pub_socket_.send( zmq::message_t( &header, sizeof( header ) ), zmq::send_flags::sndmore );
    pub_socket_.send( zmq::message_t( path.data(), path.size() * sizeof( traffic::EdgeID ) ), zmq::send_flags::none );
}

void TelemetryWorker::WorkerLoop()
{
#ifdef __linux__
    // Hard Affinity for Telemetry Thread (Core 8)
    cpu_set_t cpuset;
    CPU_ZERO( &cpuset );
    CPU_SET( 8, &cpuset ); // In production, this core ID is usually managed via TRAFFIC_TELEMETRY_AFFINITY
    pthread_setaffinity_np( pthread_self(), sizeof( cpu_set_t ), &cpuset );
#endif

    while( keep_running_ )
    {
        if( data_ready_.load( std::memory_order_acquire ) )
        {
            // Reset flag immediately
            data_ready_.store( false, std::memory_order_release );
            
            // Read from the buffer that the ENGINE JUST FINISHED WRITING (active_idx - 1)
            int send_idx = 1 - active_idx_.load( std::memory_order_acquire );
            const auto & buffer = buffers_[ send_idx ];

            if( !buffer.empty() )
            {
                // Frame 1: Telemetry Header
                pub_socket_.send( zmq::message_t( &current_header_, sizeof( current_header_ ) ), zmq::send_flags::sndmore );
                
                // Frame 2: Bulk Agent States (Zero-copy send)
                pub_socket_.send( zmq::message_t( buffer.data(), buffer.size() * sizeof( common::net::AgentState ) ), zmq::send_flags::none );
            }
        }
        
        // 25Hz Target Frequency - 40ms 
        // Note: Precision can be improved with high_resolution_clock if needed, 
        // however, this thread is non-critical for physics, only for visualization.
        std::this_thread::sleep_for( std::chrono::milliseconds( 40 ) );
    }
}

} // namespace traffic::core
