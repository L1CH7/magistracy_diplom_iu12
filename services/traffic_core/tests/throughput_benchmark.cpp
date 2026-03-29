#include <iostream>
#include <chrono>
#include <vector>
#include <random>
#include <atomic>
#include <format>
#include <thread>
#include "router/control/router_manager.hpp"
#include "common/thread_pool.hpp"
#include "common/logger.hpp"

using namespace traffic;

void RunStressTest(router::control::RouterManager& router_manager, int num_threads = 6) {
    constexpr int NUM_TASKS = 10'000;
    std::cout << "\n======================================================\n";
    std::cout << std::format("🚀 STARTING C++ INTERNAL STRESS TEST ({} Threads)\n", num_threads);
    std::cout << std::format("📦 Tasks: {}\n", NUM_TASKS);
    std::cout << "======================================================\n";

    // 1. Предварительная генерация реальных координат (берем точки из ребер графа)
    std::mt19937 gen(42); 
    auto num_edges = router_manager.num_edges();
    if (num_edges == 0) {
        std::cerr << "Error: Graph has no edges!" << std::endl;
        return;
    }
    std::uniform_int_distribution<traffic::EdgeID> dist_edge(0, num_edges - 1);

    struct TaskData { float x1, y1, x2, y2; };
    std::vector<TaskData> tasks(NUM_TASKS);
    for (int i = 0; i < NUM_TASKS; ++i) {
        auto [x1, y1] = router_manager.get_edge_coords(dist_edge(gen));
        auto [x2, y2] = router_manager.get_edge_coords(dist_edge(gen));
        tasks[i] = {x1, y1, x2, y2};
    }

    // Используем ThreadPool с включенным Affinity
    traffic::core::ThreadPool pool(num_threads, true, true); 
    alignas(64) std::atomic<int> completed_tasks{0};
    alignas(64) std::atomic<int> failed_tasks{0};

    auto start_time = std::chrono::high_resolution_clock::now();

    // 2. Асинхронная отправка задач
    for (int i = 0; i < NUM_TASKS; ++i) {
        pool.Enqueue([&router_manager, &tasks, i, &completed_tasks, &failed_tasks]() {
            auto res = router_manager.RouteByCoords(
                tasks[i].x1, tasks[i].y1, 
                tasks[i].x2, tasks[i].y2, 0
            );
            
            if (!res) failed_tasks.fetch_add(1, std::memory_order_relaxed);
            completed_tasks.fetch_add(1, std::memory_order_release);
        });
    }

    // 3. Spin-lock ожидание завершения
    while (completed_tasks.load(std::memory_order_acquire) < NUM_TASKS) {
        std::this_thread::yield();
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> duration = end_time - start_time;

    // 4. Вывод метрик
    double total_seconds = duration.count();
    double qps = NUM_TASKS / total_seconds;
    double avg_latency_ms = (total_seconds * 1000.0) / NUM_TASKS; 

    std::cout << std::format("⏱️  Total Wall-Clock Time: {:.3f} seconds\n", total_seconds);
    std::cout << std::format("❌ Failed routes: {}\n", failed_tasks.load());
    std::cout << std::format("🔥 Throughput: {:.2f} QPS\n", qps);
    std::cout << std::format("⚡ Average Latency (Wall): {:.4f} ms per request\n", avg_latency_ms);
    std::cout << "======================================================\n\n";
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <data_dir> [num_threads]" << std::endl;
        return 1;
    }

    // Инициализация логгера обязательна для использования RouterManager (LOG_xxx)
    traffic::core::logging::init_logger();

    std::string data_dir = argv[1];
    int num_threads = 12;
    if (argc >= 3) {
        num_threads = std::stoi(argv[2]);
    }

    try {
        router::control::RouterManager manager;
        std::cout << "Loading graphs from " << data_dir << "..." << std::endl;
        auto status = manager.LoadGraphs(data_dir);
        if (!status) {
            std::cerr << "Failed to load graphs: " << status.error() << std::endl;
            return 1;
        }

        RunStressTest(manager, num_threads);

    } catch (const std::exception& e) {
        std::cerr << "Benchmark error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
