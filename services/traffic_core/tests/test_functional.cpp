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
        auto res = router.Route<false, false>(0, 3, start_time, nullptr, nullptr, nullptr);
        
        CHECK(res.total_weight == 300);
        CHECK(res.path == std::vector<NodeID>{0, 1, 2, 3});
        CHECK(res.etas == std::vector<AbsoluteTime>{0, 100, 200, 300});
    }

    SUBCASE("2. Dynamic Traffic with Empty Buckets") {
        auto res = router.Route<true, false>(0, 3, start_time, vol_manager.data(), k_magic, mpr_penalty);
        CHECK(res.total_weight == 300);
    }

    SUBCASE("3. Dynamic Traffic with Congestion (BPR Penalty)") {
        std::vector<NodeID> sim_path = {1, 2};
        std::vector<AbsoluteTime> sim_etas = {50, 150}; 
        for(int i = 0; i < 50; ++i) vol_manager.book_route(sim_path, sim_etas);

        auto res = router.Route<true, false>(0, 3, start_time, vol_manager.data(), k_magic, mpr_penalty);
        CHECK(res.total_weight > 300);
        MESSAGE("Congested route weight: ", res.total_weight, "s (Expected > 300s)");
    }

    SUBCASE("4. Volume Manager Time Advancement (Ring Buffer Clear)") {
        std::vector<NodeID> sim_path = {1};
        std::vector<AbsoluteTime> sim_etas = {50}; 
        for(int i = 0; i < 50; ++i) vol_manager.book_route(sim_path, sim_etas);

        vol_manager.advance_time(0, 400);
        auto res = router.Route<true, false>(0, 3, 400, vol_manager.data(), k_magic, mpr_penalty);
        
        CHECK(res.total_weight == 300);
        CHECK(res.etas.back() == 700);
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

int main(int argc, char** argv) {
    doctest::Context context;
    context.applyCommandLine(argc, argv);
    return context.run();
}
