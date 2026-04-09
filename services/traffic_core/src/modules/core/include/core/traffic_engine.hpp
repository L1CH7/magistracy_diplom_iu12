#pragma once

#include <string>
#include <vector>
#include <memory>
#include <atomic>
#include <thread>
#include <expected>

#include "common/net/typed_endpoint.hpp"
#include "common/net/messages.hpp"
#include "common/thread_pool.hpp"
#include "router/control/router_manager.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/route_arena.hpp"
#include "data_provider/kinematics_system.hpp"
#include "decision_engine/mpr_engine.hpp"

namespace traffic::core
{

class TrafficEngine
{
public:
    TrafficEngine();
    explicit TrafficEngine( const std::vector< int > & router_cores );
    ~TrafficEngine();

    // Disable copying
    TrafficEngine( const TrafficEngine & ) = delete;
    TrafficEngine & operator=( const TrafficEngine & ) = delete;

    // Initialization
    std::expected< void, std::string > Init( const std::string & data_path );

    // Simulation Flow
    void SpawnAgents( uint32_t num_agents, uint16_t asf, const std::vector< double > & wp_probs = { 0.90, 0.05, 0.03, 0.02 } );
    void Warmup( const std::atomic<bool>* abort_flag = nullptr );
    void Warmup( uint32_t num_agents, const std::atomic<bool>* abort_flag = nullptr ); // Spawn + Warmup
    void Run(); // Uses internal atomic settings
    void Run( float requested_accel ); // Managed simulation loop
    void Step( float dt );
    void ForceReroute( const std::vector< common::net::RouteRequest > & requests );

    // Control
    void ResetState();
    void Stop();
    void PauseRouter(bool paused) { router_pool_.SetPaused(paused); }
    void SetAcceleration( float accel ) { target_accel_.store( accel ); }
    float GetCurrentAcceleration() const { return target_accel_.load(); }
    float GetCurrentFps() const { return telemetry_fps_.load(); }
    float GetCurrentChaos() const { return chaos_factor_.load(); }
    void ApplySettings( float accel, float fps, float chaos );
    void SetRespawn( bool enabled ) { respawn_enabled_.store( enabled ); }

    // Accessors for metrics
    uint32_t GetActiveAgents() const;
    size_t GetRoutesComputed() const { return routes_computed_.load(); }
    size_t GetTotalSuccessfulRoutes() const { return total_successful_routes_; }
    size_t GetTotalFailedRoutes() const { return total_failed_routes_; }
    size_t GetTotalCompletedRoutes() const { return total_completed_routes_; }
    float GetCurrentSimTime() const { return current_sim_time_; }
    const std::vector< uint32_t >& GetMaxLiveVolumes() const { return max_live_volumes_; }

    router::control::RouterManager & GetRouterManager() { return router_manager_; }
    data_provider::AgentPool & GetAgentPool() { return agent_pool_; }

    void UpdateTelemetry();
    void SetTelemetryWorker( class TelemetryWorker * worker ) { telemetry_worker_ = worker; }

private:
    void StartRouterWorker();
    void HandleResponses();
    data_provider::PhysicsContext MakePhysicsContext( uint32_t time_sec ) const noexcept;

private:
    // Modules
    router::control::RouterManager router_manager_;
    data_provider::AgentPool agent_pool_;
    data_provider::RouteArena route_arena_;
    data_provider::KinematicsSystem kin_system_;
    
    // Communication
    std::unique_ptr< common::net::TypedEndpoint< traffic::common::net::RouteRequest, traffic::common::net::RouteResponse > > mpr_ep_;
    std::unique_ptr< common::net::TypedEndpoint< traffic::common::net::RouteResponse, traffic::common::net::RouteRequest > > router_ep_;
    
    std::unique_ptr< decision_engine::MprEngine > mpr_engine_;

    // Threading
    ThreadPool router_pool_;
    std::thread router_worker_;
    std::atomic< bool >  keep_running_{ true };
    std::atomic< size_t > routes_computed_{ 0 };
    std::atomic< float > target_accel_{ 1000.0f }; // Default 1000x acceleration
    std::atomic< float > telemetry_fps_{ 25.0f };
    std::atomic< float > chaos_factor_{ 0.0f };
    std::atomic< bool >  respawn_enabled_{ true };
    std::atomic< bool >  settings_changed_{ false };
    
    size_t total_successful_routes_{ 0 };
    size_t total_failed_routes_{ 0 };
    size_t total_completed_routes_{ 0 };

    // Telemetry & Throttling
    class TelemetryWorker * telemetry_worker_{ nullptr };
    std::chrono::steady_clock::time_point last_telemetry_time_;
    std::chrono::steady_clock::time_point sim_start_real_time_;
    float sim_start_sim_time_{ 0.0f };

    // Cached buffers for zero-allocation
    std::vector< traffic::common::net::RouteRequest > mpr_requests_buffer_;

    // State
    float current_sim_time_{ 0.0f };
    uint32_t last_mpr_tick_sim_sec_{ 0 };
    uint32_t num_agents_{ 0 };
    bool is_initialized_{ false };

    // Physics cache
    std::vector< uint32_t > live_edge_volumes_;
    std::vector< uint32_t > max_live_volumes_;
    std::vector< float >    edge_lengths_cache_;
};

} // namespace traffic::core
