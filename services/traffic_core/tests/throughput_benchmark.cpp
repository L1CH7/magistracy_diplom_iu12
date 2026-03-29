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

struct RouteStats {
    std::string type;
    int pts_count;
    double wall_time_ms;
    uint32_t iterations;
    double route_duration_sec;
    size_t edges_count;
};

struct AggregatedStats {
    double t_min = 1e9, t_max = 0, t_sum = 0;
    std::vector<double> t_vals;
    
    uint32_t i_min = 0xFFFFFFFF, i_max = 0;
    uint64_t i_sum = 0;
    std::vector<uint32_t> i_vals;

    double dur_sum = 0;
    size_t edges_sum = 0;
    size_t count = 0;

    void add(const RouteStats& s) {
        t_min = std::min(t_min, s.wall_time_ms); t_max = std::max(t_max, s.wall_time_ms);
        t_sum += s.wall_time_ms; t_vals.push_back(s.wall_time_ms);

        i_min = std::min(i_min, s.iterations); i_max = std::max(i_max, s.iterations);
        i_sum += s.iterations; i_vals.push_back(s.iterations);

        dur_sum += s.route_duration_sec; edges_sum += s.edges_count;
        count++;
    }

    void finalize(std::string label) {
        if (count == 0) return;
        std::sort(t_vals.begin(), t_vals.end());
        std::sort(i_vals.begin(), i_vals.end());
        
        double t_avg = t_sum / count;
        double t_p95 = t_vals[static_cast<size_t>(count * 0.95)];
        
        double i_avg = static_cast<double>(i_sum) / count;
        uint32_t i_p95 = i_vals[static_cast<size_t>(count * 0.95)];

        double dur_avg = dur_sum / count;
        double edges_avg = static_cast<double>(edges_sum) / count;

        std::cout << std::format("{:<7} | {:>7.2f} | {:>7.2f} | {:>7.2f} | {:>7.2f} | {:>8} | {:>8} | {:>8.0f} | {:>8} | {:>9.1f} | {:>7.0f}\n",
            label, t_min, t_max, t_avg, t_p95, i_min, i_max, i_avg, i_p95, dur_avg, edges_avg);
    }
};

void PrintHeader(std::string title) {
    std::cout << "\n=== " << title << " ===\n";
    std::cout << std::format("{:<7} | {:>7} | {:>7} | {:>7} | {:>7} | {:>8} | {:>8} | {:>8} | {:>8} | {:>9} | {:>7}\n",
        "GRP/PTS", "T-MIN", "T-MAX", "T-AVG", "T-P95", "I-MIN", "I-MAX", "I-AVG", "I-P95", "DUR(sec)", "EDGES");
    std::cout << std::string(105, '-') << "\n";
}

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
                    static_cast<double>(res->total_weight),
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

    std::map<int, AggregatedStats> id_stats, ll_stats;
    AggregatedStats total_id, total_ll, total_all;

    for (const auto& th_res : thread_results) {
        for (const auto& s : th_res) {
            total_all.add(s);
            if (s.type == "ID") { id_stats[s.pts_count].add(s); total_id.add(s); } 
            else { ll_stats[s.pts_count].add(s); total_ll.add(s); }
        }
    }

    PrintHeader("DIRECT ID ROUTING");
    for (int i = 2; i <= 5; ++i) id_stats[i].finalize(std::to_string(i) + " PTS");
    std::cout << std::string(105, '-') << "\n";
    total_id.finalize("ALL ID");

    PrintHeader("COORDINATE SNAP (LL) ROUTING");
    for (int i = 2; i <= 5; ++i) ll_stats[i].finalize(std::to_string(i) + " PTS");
    std::cout << std::string(105, '-') << "\n";
    total_ll.finalize("ALL LL");

    PrintHeader("OVERALL SYSTEM");
    total_all.finalize("GLOBAL");

    std::cout << "\n🔥 Global Throughput: " << NUM_TASKS / total_seconds << " QPS (Full System Wall Time)\n";
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
