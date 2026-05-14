#pragma once

#include <atomic>
#include <thread>
#include <vector>
#include <array>
#include <mutex>
#include <span>
#include <zmq.hpp>

#include "common/net/telemetry_protocol.hpp"

namespace traffic::core
{

/**
 * @brief Zero-latency Telemetry Dispatcher using Double Buffering and ZeroMQ PUB.
 * Designed to separate high-frequency physics from network I/O.
 */
class TelemetryWorker
{
public:
    explicit TelemetryWorker( zmq::context_t & context, uint32_t max_agents = 1000000 );
    ~TelemetryWorker();

    // Disable copying
    TelemetryWorker( const TelemetryWorker & ) = delete;
    TelemetryWorker & operator=( const TelemetryWorker & ) = delete;

    /**
     * @brief Start the publisher thread. Binder to "tcp://*:5556".
     */
    void Start( const std::string & bind_addr = "tcp://*:5556" );
    void Stop();

    /**
     * @brief Get the buffer currently not being sent, for the engine to write to.
     */
    std::vector< common::net::AgentState > & GetInactiveBuffer() 
    { 
        return buffers_[ 1 - active_idx_.load( std::memory_order_relaxed ) ]; 
    }

    /**
     * @brief Swap buffers and notify the worker thread that new telemetry is ready.
     * Called by TrafficEngine at the end of its hot cycle (or at 25Hz threshold).
     */
    void Publish( const common::net::TelemetryHeader & header );

    /**
     * @brief Publish heatmap volume snapshot (~1Hz).
     * Sends HeatmapHeader + HeatmapEntry[] as a separate ZMQ multipart message.
     * Thread-safe (uses event_mutex_).
     */
    void PublishHeatmap( const common::net::HeatmapHeader & header,
                         std::span< const common::net::HeatmapEntry > entries );

    /**
     * @brief Send a discrete event packet (SPAWN/REROUTE) with a path payload.
     * Sent immediately as a separate multi-frame message.
     */
    void SendEvent( common::net::EventType type, uint32_t agent_id, std::span< const traffic::EdgeID > path );

private:
    void WorkerLoop();

private:
    zmq::socket_t pub_socket_;
    
    // Double buffering (Zero-mutex hot path)
    std::array< std::vector< common::net::AgentState >, 2 > buffers_;
    common::net::TelemetryHeader current_header_{};
    
    std::atomic< int > active_idx_{ 0 };
    std::atomic< bool > data_ready_{ false };
    std::atomic< bool > keep_running_{ false };
    
    std::thread worker_thread_;
    std::mutex event_mutex_; // Events and heatmap are rare, mutex is acceptable here
};

} // namespace traffic::core
