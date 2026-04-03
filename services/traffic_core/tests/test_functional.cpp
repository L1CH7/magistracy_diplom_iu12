#define DOCTEST_CONFIG_IMPLEMENT
#include "doctest.h"
#include <vector>
#include <iostream>
#include <random>
#include <chrono>
#include <atomic>
#include <thread>

#include "router/compute/td_alt_router.hpp"
#include "router/control/volume_manager.hpp"
#include "router/control/router_manager.hpp"
#include "common/graph_types.hpp"
#include "common/thread_pool.hpp"
#include "common/logger.hpp"
#include "common/net/typed_endpoint.hpp"
#include "common/net/inproc_transport.hpp"
#include "common/net/message_pool.hpp"
#include "data_provider/agent_pool.hpp"
#include "data_provider/route_arena.hpp"
#include "data_provider/kinematics_system.hpp"
#include "decision_engine/mpr_engine.hpp"

using namespace traffic;

// Глобальный путь к данным для бенчмарка
static std::string g_data_dir = "";

TEST_CASE("Traffic Core Routing & Volume Management Functional Test") {
    // === ИНИЦИАЛИЗАЦИЯ ОБЩЕГО СОСТОЯНИЯ (Выполняется для каждого SUBCASE) ===
    
    // Граф-линия: 0 -> 1 -> 2 -> 3
    EdgeID row_ptr[] = {0, 1, 2, 3, 3};
    NodeID col_ind[] = {1, 2, 3};
    EdgeWeight weights[] = {100, 100, 100}; // T_free = 100s на сегмент
    
    GraphView view{row_ptr, col_ind, weights};
    uint32_t num_nodes = 4;

    PenaltyScale k_magic[] = {0, 100000, 100000, 0}; 
    EdgeWeight mpr_penalty[] = {0, 0, 0, 0};

    router::compute::TdAltRouter router(view, num_nodes);
    router::control::VolumeManager vol_manager(num_nodes);
    AbsoluteTime start_time = 0;

    SUBCASE("1. Free Flow Routing (Traffic = false)") {
        MESSAGE("Testing A* Free Flow Routing on 4-node linear graph (0->1->2->3)");
        auto res = router.Route<false, false>(0, 3, start_time, nullptr, nullptr, nullptr);
        
        CHECK(res.total_weight == 300);
        CHECK(res.path == std::vector<NodeID>{0, 1, 2, 3});
        CHECK(res.etas == std::vector<AbsoluteTime>{0, 100, 200, 300});
        MESSAGE("  [Result] Total weight: ", res.total_weight, "s (Expected 300s)");
    }

    SUBCASE("2. Dynamic Traffic with Empty Buckets") {
        MESSAGE("Testing Dynamic Traffic with zero occupancy in buckets...");
        auto res = router.Route<true, false>(0, 3, start_time, vol_manager.data(), k_magic, mpr_penalty);
        CHECK(res.total_weight == 300);
        MESSAGE("  [Result] Path weight remains 300s (No congestion)");
    }

    SUBCASE("3. Dynamic Traffic with Congestion (BPR Penalty)") {
        MESSAGE("Testing Congestion Penalty (BPR) with 50 agents booked on segments 1->2...");
        std::vector<NodeID> sim_path = {1, 2};
        std::vector<AbsoluteTime> sim_etas = {50, 150}; 
        for(int i = 0; i < 50; ++i) vol_manager.book_route(sim_path, sim_etas);

        auto res = router.Route<true, false>(0, 3, start_time, vol_manager.data(), k_magic, mpr_penalty);
        CHECK(res.total_weight > 300);
        MESSAGE("  [Result] Congested route weight: ", res.total_weight, "s (Expected > 300s)");
    }

    SUBCASE("4. Volume Manager Time Advancement (Ring Buffer Clear)") {
        MESSAGE("Testing Volume Manager time advancement (t=0 to t=400)...");
        std::vector<NodeID> sim_path = {1};
        std::vector<AbsoluteTime> sim_etas = {50}; 
        for(int i = 0; i < 50; ++i) vol_manager.book_route(sim_path, sim_etas);

        vol_manager.advance_time(0, 400);
        auto res = router.Route<true, false>(0, 3, 400, vol_manager.data(), k_magic, mpr_penalty);
        
        CHECK(res.total_weight == 300);
        CHECK(res.etas.back() == 700);
        MESSAGE("  [Result] Old traffic cleared. Route weight back to 300s.");
    }

    SUBCASE("5. Unbooking Routes (Cancellation)") {
        std::vector<NodeID> sim_path = {1};
        std::vector<AbsoluteTime> sim_etas = {50}; 
        for(int i = 0; i < 10; ++i) vol_manager.book_route(sim_path, sim_etas);
        for(int i = 0; i < 10; ++i) vol_manager.unbook_route(sim_path, sim_etas);

        auto res = router.Route<true, false>(0, 3, start_time, vol_manager.data(), k_magic, mpr_penalty);
        CHECK(res.total_weight == 300);
    }
}

TEST_CASE( "Zero-Allocation Communication Layer Unit Test" )
{
    using namespace traffic::common::net;

    SUBCASE( "1. MessagePool basic Acquire/Release" )
    {
        MESSAGE("Testing MessagePool: acquire new buffer -> release -> acquire reused buffer...");
        MessagePool pool;
        auto buf = pool.Acquire();
        CHECK( buf.empty() );
        
        buf.push_back( 42 );
        size_t cap = buf.capacity();
        pool.Release( std::move( buf ) );
        
        auto buf2 = pool.Acquire();
        CHECK( buf2.empty() );
        CHECK( buf2.capacity() >= cap ); // Capacity preserved
        MESSAGE("  [OK] Buffer capacity preserved (", cap, " bytes)");
    }

    SUBCASE( "2. TypedEndpoint round-trip (std::vector<int>)" )
    {
        MESSAGE("Testing TypedEndpoint: sending std::vector<int>{1, 2, 3, 4, 5} via InProcTransport...");
        auto transport = std::make_unique< InProcTransport >();
        TypedEndpoint< int, int > endpoint( std::move( transport ) );

        std::vector< int > sent_data = { 1, 2, 3, 4, 5 };
        endpoint.Send( sent_data );

        std::vector< int > received_data;
        bool has_data = endpoint.Receive( received_data );

        CHECK( has_data );
        CHECK( received_data == sent_data );
        CHECK( received_data.size() == 5 );
        MESSAGE("  [SUCCESS] Received exactly the same 5 integers.");
    }

    SUBCASE( "3. Zero-Allocation check (Capacity Preservation)" )
    {
        MESSAGE("Testing Zero-Allocation: checking if receiver's vector capacity is preserved...");
        auto transport = std::make_unique< InProcTransport >();
        TypedEndpoint< uint64_t, uint64_t > endpoint( std::move( transport ) );

        std::vector< uint64_t > buffer;
        buffer.reserve( 100 ); // Pre-allocate
        size_t initial_cap = buffer.capacity();

        std::vector< uint64_t > data_to_send( 10, 0xDEADBEEFull );
        endpoint.Send( data_to_send );

        bool ok = endpoint.Receive( buffer );
        CHECK( ok );
        CHECK( buffer.size() == 10 );
        CHECK( buffer.capacity() >= initial_cap ); // Capacity should not be lost
        MESSAGE("  [OK] Capacity ", initial_cap, " kept after ReceiveBytes.");
    }
}

TEST_CASE( "Mesoscopic Simulation (Data Provider) Functional Test" )
{
    using namespace traffic::data_provider;

    RouteArena arena;
    AgentPool pool;
    KinematicsSystem system( pool, arena );

    // Setup: 1 agent, 2 edges (100m each)
    uint32_t agent_id = 0;
    std::vector< traffic::EdgeID > route = { 101, 102 };
    std::vector< uint32_t > etas = { 100, 200 };
    arena.UpdateRoute( agent_id, route, etas );

    pool.Allocate( 1 );
    pool.is_active[ agent_id ] = 1;
    pool.current_edge[ agent_id ] = route[ 0 ];
    pool.velocity_mps[ agent_id ] = 10.0f;      // 10 m/s
    pool.inv_edge_length_m[ agent_id ] = 0.01f; // 1/100m (Total length 100m)
    pool.route_progress_idx[ agent_id ] = 0;

    SUBCASE( "1. Simple Kinematic Advancement" )
    {
        MESSAGE("Testing Kinematics: 10m/s for 1s update...");
        system.AdvanceKinematics( 1.0f ); // Move for 1s (10m)
        
        CHECK( pool.pos_meters[ agent_id ] == doctest::Approx( 10.0f ) );
        CHECK( pool.transition_queue.empty() );
        MESSAGE("  [OK] Position is exactly 10.0m.");
    }

    SUBCASE( "2. Edge Transition (Jump to second edge)" )
    {
        MESSAGE("Testing Edge Transition: move 110m (edge length 100m) -> check overflight...");
        // 11s at 10m/s = 110m total. Edge length is 100m. 
        // We expect transition with 10m overflight on the next edge.
        system.AdvanceKinematics( 11.0f ); 
        
        REQUIRE( pool.transition_queue.size() == 1 );
        CHECK( pool.transition_queue[ 0 ] == agent_id );

        system.ProcessTransitions( 11 );
        
        // After transition: 
        // pos_meters = 110 - 100 = 10m
        // current_edge = 102
        // route_progress_idx = 1
        CHECK( pool.pos_meters[ agent_id ] == doctest::Approx( 10.0f ) );
        CHECK( pool.current_edge[ agent_id ] == 102 );
        CHECK( pool.route_progress_idx[ agent_id ] == 1 );
        CHECK( pool.is_active[ agent_id ] == 1 );
        MESSAGE("  [OK] Agent moved to edge 102, position corrected to 10.0m.");
    }

    SUBCASE( "3. Route Completion (Despawn)" )
    {
        MESSAGE("Testing Route Completion: moving 10m when only 5m left on the last edge...");
        // Start on the last edge
        pool.route_progress_idx[ agent_id ] = 1;
        pool.current_edge[ agent_id ] = 102;
        pool.pos_meters[ agent_id ] = 95.0f; // 5m before end

        system.AdvanceKinematics( 1.0f ); // Move 10m -> 105m pos.
        system.ProcessTransitions( 1 );
        
        // End of route detected
        CHECK( pool.is_active[ agent_id ] == 0 );
        CHECK( pool.pos_meters[ agent_id ] == 0.0f );
        MESSAGE("  [OK] Agent successfully despawned (is_active = 0).");
    }
}

TEST_CASE( "MPR Engine (Decision Engine) Functional Test" )
{
    using namespace traffic;
    using namespace traffic::common::net;
    using namespace traffic::data_provider;
    using namespace traffic::decision_engine;

    // Setup: 10 agent slots
    AgentPool pool;
    pool.Allocate( 10 );
    RouteArena arena;

    // Simulate Router (Endpoint 1) and MPR (Endpoint 2)
    auto mpr_transport = std::make_unique< InProcTransport >();
    auto router_transport = std::make_unique< InProcTransport >();
    
    // Link transports to form a pipe (Bi-directional)
    mpr_transport->SetRemote( router_transport.get() );
    router_transport->SetRemote( mpr_transport.get() );

    TypedEndpoint< RouteRequest, traffic::common::net::RouteResponse > mpr_ep( std::move( mpr_transport ) );
    TypedEndpoint< traffic::common::net::RouteResponse, RouteRequest > router_ep( std::move( router_transport ) );

    MprEngine engine;

    SUBCASE( "1. Phase 1: Route Application (Manual via Arena)" )
    {
        MESSAGE("Testing Manual Route Application to Agent 5...");
        
        uint32_t agent_id = 5;
        traffic::common::net::RouteResponse resp {};
        resp.agent_id = agent_id;
        resp.success = true;
        resp.path_len = 3;
        resp.path[ 0 ] = 100;
        resp.path[ 1 ] = 101;
        resp.path[ 2 ] = 102;
        resp.edge_etas_sec[ 0 ] = 60;
        resp.edge_etas_sec[ 1 ] = 120;
        resp.edge_etas_sec[ 2 ] = 180;

        // Apply manually as MprEngine no longer handles internal receiving
        arena.UpdateRoute( agent_id, 
                           { resp.path.data(), resp.path_len },
                           { resp.edge_etas_sec.data(), resp.path_len } );
        pool.route_progress_idx[ agent_id ] = 0;
        pool.edge_enter_time_sec[ agent_id ] = 1000;
        pool.current_edge[ agent_id ] = 100;

        // Verify Arena
        auto path = arena.GetRoute( agent_id );
        REQUIRE( path.size() == 3 );
        CHECK( path[ 0 ] == 100 );

        auto etas = arena.GetEtas( agent_id );
        REQUIRE( etas.size() == 3 );
        CHECK( etas[ 0 ] == 60 );

        // Verify Pool
        CHECK( pool.route_progress_idx[ agent_id ] == 0 );
        CHECK( pool.edge_enter_time_sec[ agent_id ] == 1000 );
        CHECK( pool.current_edge[ agent_id ] == 100 );
        MESSAGE("  [SUCCESS] Route applied manually, state verified.");
    }

    SUBCASE( "2. Reroute Detection (Tolerance 1.5x)" )
    {
        MESSAGE("Testing MPR Reroute detection logic...");
        uint32_t agent_id = 0;
        pool.is_active[ agent_id ] = 1;
        pool.current_edge[ agent_id ] = 500;
        pool.target_edge[ agent_id ] = 999; // Destination
        pool.route_progress_idx[ agent_id ] = 0;
        pool.edge_enter_time_sec[ agent_id ] = 1000;

        std::vector< traffic::EdgeID > path = { 500, 501 };
        std::vector< uint32_t > etas = { 100, 200 };
        arena.UpdateRoute( agent_id, path, etas ); // Expected 100s for first edge

        std::vector< RouteRequest > requests;

        // Test A: Within tolerance (elapsed = 140s, expected = 100s, ratio = 1.4 < 1.5)
        engine.Tick( 1140, pool, arena, requests );
        CHECK( requests.empty() );
        MESSAGE("  [OK] No reroute for 1.4x delay.");

        // Test B: Exceeds tolerance (elapsed = 160s, expected = 100s, ratio = 1.6 > 1.5)
        engine.Tick( 1160, pool, arena, requests );
        REQUIRE( !requests.empty() );
        CHECK( requests[ 0 ].agent_id == agent_id );
        CHECK( requests[ 0 ].start_edge == 500 );
        CHECK( requests[ 0 ].target_edge == 999 );
        MESSAGE("  [OK] Reroute request generated for 1.6x delay.");
    }

    SUBCASE( "3. Multi-agent Batch Scan" )
    {
        MESSAGE("Testing MPR Batch Scan: 10 agents (5 delayed, 5 on time)...");
        uint32_t start_time = 1000;
        
        for( uint32_t i = 0; i < 10; ++i )
        {
            pool.is_active[ i ] = 1;
            pool.edge_enter_time_sec[ i ] = start_time;
            pool.route_progress_idx[ i ] = 0;
            pool.target_edge[ i ] = 2000 + i;
            
            std::vector< traffic::EdgeID > path = { 1000 };
            std::vector< uint32_t > etas = { 100 };
            arena.UpdateRoute( i, path, etas ); // All expect 100s
        }

        // 0-4 are delayed (160s elapsed), 5-9 are okay (110s elapsed)
        uint32_t current_time = start_time + 160;
        for( uint32_t i = 5; i < 10; ++i )
        {
            pool.edge_enter_time_sec[ i ] = start_time + 70; // Only 90s elapsed
        }

        std::vector< RouteRequest > requests;
        engine.Tick( current_time, pool, arena, requests );
        
        CHECK( requests.size() == 5 ); // Only agents 0, 1, 2, 3, 4 should be stuck
        for( size_t i = 0; i < requests.size(); ++i )
        {
            CHECK( requests[ i ].agent_id == static_cast< uint32_t >( i ) );
            CHECK( requests[ i ].target_edge == 2000 + i );
        }
        MESSAGE("  [SUCCESS] Batch scan correctly identified exactly 5 delayed agents.");
    }
}

int main(int argc, char** argv) {
    doctest::Context context;
    context.applyCommandLine(argc, argv);
    return context.run();
}
