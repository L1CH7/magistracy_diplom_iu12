#include <iostream>
#include <chrono>
#include <vector>
#include <random>
#include <atomic>
#include <format>
#include <thread>
#include <algorithm>
#include <iomanip>
#include <map>

#define DOCTEST_CONFIG_IMPLEMENT
#include "doctest.h"

#include "router/control/router_manager.hpp"
#include "common/thread_pool.hpp"
#include "common/logger.hpp"

using namespace traffic;

// Глобальный путь к данным для бенчмарка
static std::string g_data_path = "";

// --- Аналитические структуры ---
struct RouteStats {
    std::string type;
    int pts_count;
    double wall_time_ms;
    uint32_t iterations;
    size_t edges_count;
};

struct AggStats {
    double t_sum = 0, t_max = 0;
    uint64_t i_sum = 0;
    
    // Для медиан и перцентилей нормализованных метрик
    std::vector<double> ns_per_iter_vals;
    std::vector<double> iter_per_edge_vals;
    
    size_t count = 0;

    void add(const RouteStats& s) {
        t_sum += s.wall_time_ms;
        t_max = std::max(t_max, s.wall_time_ms);
        i_sum += s.iterations;
        
        if (s.iterations > 0) {
            ns_per_iter_vals.push_back((s.wall_time_ms * 1e6) / s.iterations);
        }
        if (s.edges_count > 0) {
            iter_per_edge_vals.push_back(static_cast<double>(s.iterations) / s.edges_count);
        }
        count++;
    }

    void print(std::string label, int total_threads) {
        if (count == 0) return;
        
        std::sort(ns_per_iter_vals.begin(), ns_per_iter_vals.end());
        std::sort(iter_per_edge_vals.begin(), iter_per_edge_vals.end());
        
        double t_avg = t_sum / count;
        double i_avg = static_cast<double>(i_sum) / count;
        
        double ns_iter_avg = 0;
        if (!ns_per_iter_vals.empty()) {
            for (double v : ns_per_iter_vals) ns_iter_avg += v;
            ns_iter_avg /= ns_per_iter_vals.size();
        }
        
        double ns_iter_p95 = !ns_per_iter_vals.empty() 
            ? ns_per_iter_vals[static_cast<size_t>(ns_per_iter_vals.size() * 0.95)] : 0;
        
        double iter_edge_avg = 0;
        if (!iter_per_edge_vals.empty()) {
            for (double v : iter_per_edge_vals) iter_edge_avg += v;
            iter_edge_avg /= iter_per_edge_vals.size();
        }
        
        double iter_edge_max = !iter_per_edge_vals.empty() ? iter_per_edge_vals.back() : 0;

        // Эффективный QPS = (Кол-во задач * Потоки) / Суммарное время процессора в секундах
        double eff_qps = (t_sum > 0) ? (count * total_threads) / (t_sum / 1000.0) : 0;

        std::cout << std::format("{:<7} | {:>7.2f} | {:>7.2f} | {:>8.0f} | {:>9.1f} | {:>9.1f} | {:>9.1f} | {:>9.1f} | {:>8.0f}\n",
            label, t_avg, t_max, i_avg, ns_iter_avg, ns_iter_p95, iter_edge_avg, iter_edge_max, eff_qps);
    }
};

TEST_CASE("Analytical Throughput Benchmark" * doctest::skip(true)) {
    router::control::RouterManager router_manager;
    try {
        router_manager.LoadGraphs(g_data_path);
    } catch (...) {
        FAIL("Could not load graphs from " << g_data_path);
    }

    int num_threads = std::thread::hardware_concurrency();
    constexpr int NUM_TASKS = 20000;

    std::cout << "\n======================================================\n";
    std::cout << std::format("🚀 STARTING ANALYTICAL BENCHMARK ({} Threads)\n", num_threads);
    std::cout << std::format("📦 Total Requests: {}\n", NUM_TASKS);
    std::cout << "======================================================\n";

    std::mt19937 gen(42); 
    auto num_edges = router_manager.num_edges();
    if (num_edges == 0) return;
    std::uniform_int_distribution<traffic::NodeID> dist_node(0, num_edges - 1);
    std::uniform_int_distribution<int> dist_pts(2, 5);
    std::uniform_int_distribution<int> dist_type(0, 1); // 0=ID, 1=LL

    struct TaskReq {
        std::string type;
        std::vector<traffic::NodeID> ids;
        std::vector<std::pair<float, float>> coords;
    };
    std::vector<TaskReq> tasks(NUM_TASKS);

    for (int i = 0; i < NUM_TASKS; ++i) {
        int pts = dist_pts(gen);
        tasks[i].type = (dist_type(gen) == 0) ? "ID" : "LL";
        for (int p = 0; p < pts; ++p) {
            auto node = dist_node(gen);
            tasks[i].ids.push_back(node);
            tasks[i].coords.push_back(router_manager.get_edge_coords(node));
        }
    }

    traffic::core::ThreadPool pool(num_threads); 
    std::atomic<int> completed_tasks{0};
    
    std::vector<std::vector<RouteStats>> thread_results(num_threads);
    for (auto& vec : thread_results) vec.reserve(NUM_TASKS / num_threads + 100);

    auto start_time = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < NUM_TASKS; ++i) {
        pool.Enqueue([&router_manager, &tasks, i, &completed_tasks, &thread_results, num_threads]() {
            int thread_id = i % num_threads;
            auto t_start = std::chrono::high_resolution_clock::now();
            
            auto res = (tasks[i].type == "ID") 
                ? router_manager.Route<false, true>(tasks[i].ids, 0) 
                : router_manager.Route<false, true>(tasks[i].coords, 0);

            auto t_end = std::chrono::high_resolution_clock::now();
            double duration_ms = std::chrono::duration<double, std::milli>(t_end - t_start).count();

            if (res) {
                thread_results[thread_id].push_back({
                    tasks[i].type,
                    static_cast<int>(tasks[i].ids.size()),
                    duration_ms,
                    res->visited_nodes_count,
                    res->path.size()
                });
            }
            completed_tasks.fetch_add(1, std::memory_order_release);
        });
    }

    while (completed_tasks.load(std::memory_order_acquire) < NUM_TASKS) {
        std::this_thread::yield();
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    double total_seconds = std::chrono::duration<double>(end_time - start_time).count();

    std::map<int, AggStats> id_stats, ll_stats;
    AggStats total_id, total_ll, total_all;

    for (const auto& th_res : thread_results) {
        for (const auto& s : th_res) {
            total_all.add(s);
            if (s.type == "ID") { id_stats[s.pts_count].add(s); total_id.add(s); } 
            else { ll_stats[s.pts_count].add(s); total_ll.add(s); }
        }
    }

    auto print_hdr = [](std::string title) {
        std::cout << "\n=== " << title << " ===\n";
        std::cout << std::format("{:<7} | {:>7} | {:>7} | {:>8} | {:>9} | {:>9} | {:>9} | {:>9} | {:>8}\n",
            "GRP/PTS", "T-AVG", "T-MAX", "I-AVG", "ns/Iter", "ns/Iter95", "Iter/Edge", "I/E(MAX)", "EFF-QPS");
        std::cout << std::string(100, '-') << "\n";
    };

    print_hdr("DIRECT ID ROUTING");
    for (int i = 2; i <= 5; ++i) id_stats[i].print(std::to_string(i) + " PTS", num_threads);
    std::cout << std::string(100, '-') << "\n";
    total_id.print("ALL ID", num_threads);

    print_hdr("COORDINATE SNAP (LL) ROUTING");
    for (int i = 2; i <= 5; ++i) ll_stats[i].print(std::to_string(i) + " PTS", num_threads);
    std::cout << std::string(100, '-') << "\n";
    total_ll.print("ALL LL", num_threads);

    print_hdr("OVERALL SYSTEM");
    total_all.print("GLOBAL", num_threads);

    std::cout << "\n🔥 Global Wall-Clock Throughput: " << NUM_TASKS / total_seconds << " QPS\n\n";
}

int main(int argc, char** argv) {
    doctest::Context context;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--data" && i + 1 < argc) {
            g_data_path = argv[i + 1];
            for(int j = i; j < argc - 2; ++j) argv[j] = argv[j+2];
            argc -= 2;
            i--;
        }
    }

    context.applyCommandLine(argc, argv);
    
    if (!g_data_path.empty()) {
        context.setOption("no-skip", true);
        traffic::core::logging::init_logger();
    }

    return context.run();
}
