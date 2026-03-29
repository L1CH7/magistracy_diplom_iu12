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

TEST_CASE("Stress Test / Benchmark" * doctest::description("Heavy stress test on real graph") * doctest::skip(true)) {
    if (g_data_dir.empty()) {
        MESSAGE("Skipping benchmark: no data directory provided (use --data <path>)");
        return;
    }

    router::control::RouterManager manager;
    auto status = manager.LoadGraphs(g_data_dir);
    REQUIRE_MESSAGE(status, "Failed to load graphs from " << g_data_dir);

    constexpr int NUM_TASKS = 10000;
    int num_threads = std::thread::hardware_concurrency();
    if (num_threads > 12) num_threads = 12;

    std::cout << "\n======================================================\n";
    std::cout << "🚀 STARTING DOCTEST STRESS TEST (" << num_threads << " Threads)\n";
    std::cout << "======================================================\n";

    std::mt19937 gen(42);
    auto num_edges = manager.num_edges();
    std::uniform_int_distribution<traffic::EdgeID> dist_edge(0, num_edges - 1);

    struct TaskData { float x1, y1, x2, y2; };
    std::vector<TaskData> tasks(NUM_TASKS);
    for (int i = 0; i < NUM_TASKS; ++i) {
        auto [x1, y1] = manager.get_edge_coords(dist_edge(gen));
        auto [x2, y2] = manager.get_edge_coords(dist_edge(gen));
        tasks[i] = {x1, y1, x2, y2};
    }

    traffic::core::ThreadPool pool(num_threads, true, true);
    std::atomic<int> completed_tasks{0};
    std::atomic<int> failed_tasks{0};

    auto start_time = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < NUM_TASKS; ++i) {
        pool.Enqueue([&manager, &tasks, i, &completed_tasks, &failed_tasks]() {
            auto res = manager.Route<false, false>(
                tasks[i].x1, tasks[i].y1, 
                tasks[i].x2, tasks[i].y2, 0
            );
            if (!res) failed_tasks.fetch_add(1, std::memory_order_relaxed);
            completed_tasks.fetch_add(1, std::memory_order_release);
        });
    }

    while (completed_tasks.load(std::memory_order_acquire) < NUM_TASKS) {
        std::this_thread::yield();
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    double total_seconds = std::chrono::duration<double>(end_time - start_time).count();
    
    std::cout << "⏱️  Total Wall-Clock Time: " << total_seconds << " seconds\n";
    std::cout << "❌ Failed routes: " << failed_tasks.load() << "\n";
    std::cout << "🔥 Throughput: " << NUM_TASKS / total_seconds << " QPS\n";
    std::cout << "======================================================\n\n";

    CHECK(failed_tasks.load() == 0);
}

int main(int argc, char** argv) {
    doctest::Context context;

    // Кастомный парсинг аргумента --data
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--data" && i + 1 < argc) {
            g_data_dir = argv[i + 1];
            // Убираем эти аргументы из списка для doctest, 
            // чтобы он не ругался на неизвестный флаг
            for(int j = i; j < argc - 2; ++j) argv[j] = argv[j+2];
            argc -= 2;
            i--;
        }
    }

    context.applyCommandLine(argc, argv);
    
    // Если указана дата, принудительно включаем бенчмарк (убираем skip)
    if (!g_data_dir.empty()) {
        context.setOption("no-skip", true);
        
        // Также инициализируем логгер, так как RouterManager его использует
        traffic::core::logging::init_logger();
    }

    return context.run();
}
