#include <iostream>
#include <chrono>
#include <vector>
#include <random>
#include <iomanip>
#include <format>
#include <stdexcept>
#include <filesystem>
#include <csignal>
#include <csetjmp>
#include "router/control/router_manager.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/compute/dijkstra_router.hpp"
#include "router/compute/advanced_pqs.hpp"

using namespace traffic;
using namespace traffic::router::compute;

// Global state for signal handling
static sigjmp_buf g_jump_buffer;
static volatile sig_atomic_t g_test_in_progress = 0;
static volatile sig_atomic_t g_current_route_idx = 0;

void signal_handler(int sig) {
    if (g_test_in_progress) {
        siglongjmp(g_jump_buffer, sig);
    } else {
        std::cerr << "\nFatal signal " << sig << " received outside of test context. Aborting.\n";
        std::exit(sig);
    }
}

struct TestGuard {
    TestGuard() { g_test_in_progress = 1; }
    ~TestGuard() { g_test_in_progress = 0; }
};

struct RouteTask {
    NodeID source;
    NodeID target;
};

struct BenchResult {
    std::string name;
    double total_ms = 0;
    double avg_ns_per_iter = 0;
    double avg_iters = 0;
    double qps = 0;
    double correctness = 0;
    size_t completed_routes = 0;
    bool failed = false;
    bool crashed = false;
};

template<template<typename> class RouterType, typename PQType>
BenchResult RunTestProtected(const std::string& name, 
                             const std::vector<RouteTask>& tasks,
                             GraphView view, 
                             NodeID num_nodes,
                             const uint16_t* landmarks,
                             const RoutingResult* baseline_results = nullptr) 
{
    std::cout << "  - Starting test: " << name << "... " << std::flush;
    
    BenchResult res;
    res.name = name;
    
    int sig = sigsetjmp(g_jump_buffer, 1);
    if (sig == 0) {
        g_current_route_idx = 0;
        {
            TestGuard guard;
            try {
                RouterType<PQType> router_instance(view, num_nodes);
                // Try to set landmarks only if RouterType supports it
                if constexpr (requires(RouterType<PQType> r, const uint16_t* l) { r.get_heuristic().set_landmarks((const EdgeWeight*)l); }) {
                    if (landmarks) {
                        router_instance.get_heuristic().set_landmarks(reinterpret_cast<const EdgeWeight*>(landmarks));
                    }
                }

                uint64_t total_iters = 0;
                uint32_t correct_count = 0;
                
                auto start = std::chrono::high_resolution_clock::now();
                for (size_t i = 0; i < tasks.size(); ++i) {
                    g_current_route_idx = i;
                    auto route_res = router_instance.template Route<false, true>(tasks[i].source, tasks[i].target);
                    
                    total_iters += route_res.visited_nodes_count;
                    if (baseline_results) {
                        if (route_res.total_weight != baseline_results[i].total_weight) {
                            bool acceptable_mismatch = false;
                            if (baseline_results[i].total_weight != 0xFFFFFFFF && route_res.total_weight != 0xFFFFFFFF && baseline_results[i].total_weight > 0) {
                                double diff_pct = std::abs(static_cast<double>(route_res.total_weight) - baseline_results[i].total_weight) / baseline_results[i].total_weight * 100.0;
                                if (diff_pct <= 15.0) {
                                    acceptable_mismatch = true;
                                }
                            }
                            if (!acceptable_mismatch) {
                                std::cerr << std::format("\n[ROUTE ERROR] Task {} ({} -> {}): weight mismatch! Expected {}, got {}\n", 
                                                         i, tasks[i].source, tasks[i].target, baseline_results[i].total_weight, route_res.total_weight);
                                throw std::runtime_error("Route weight mismatch!");
                            }
                        }
                        if (baseline_results[i].total_weight != 0xFFFFFFFF && route_res.path.empty() && baseline_results[i].total_weight > 0) {
                            std::cerr << std::format("\n[ROUTE ERROR] Task {} ({} -> {}): empty path for valid weight!\n", i, tasks[i].source, tasks[i].target);
                            throw std::runtime_error("Empty path in routing result!");
                        }
                        correct_count++;
                    } else {
                        correct_count++;
                    }
                    res.completed_routes++;
                }
                auto end = std::chrono::high_resolution_clock::now();
                
                res.total_ms = std::chrono::duration<double, std::milli>(end - start).count();
                res.avg_iters = static_cast<double>(total_iters) / (res.completed_routes > 0 ? res.completed_routes : 1);
                res.avg_ns_per_iter = (total_iters > 0) ? (res.total_ms * 1e6 / total_iters) : 0;
                res.qps = (res.total_ms > 0) ? (res.completed_routes * 1000.0 / res.total_ms) : 0;
                res.correctness = (res.completed_routes > 0) ? (static_cast<double>(correct_count) / res.completed_routes * 100.0) : 0;
                
                std::cout << "Done.\n";
            } catch (const std::exception& e) {
                res.failed = true;
                std::cout << "FAILED: " << e.what() << "\n";
            }
        }
    } else {
        res.crashed = true;
        res.failed = true;
        std::cout << " !!! CRASHED !!!\n";
    }
    
    return res;
}

int main(int argc, char** argv) {
    std::signal(SIGSEGV, signal_handler);
    std::signal(SIGABRT, signal_handler);
    std::signal(SIGILL,  signal_handler);
    std::signal(SIGFPE,  signal_handler);

    std::string data_path = "/app/data";
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--data" && i + 1 < argc) {
            data_path = argv[i+1];
        }
    }

    router::control::RouterManager manager;
    if (!manager.LoadGraphs(data_path)) {
        std::cerr << "Failed to load graphs from " << data_path << "\n";
        return 1;
    }

    auto view = manager.get_view();
    auto num_nodes = manager.num_nodes();
    const uint16_t* landmarks = manager.get_landmarks_ptr();
    
    std::mt19937 gen(42);
    std::uniform_int_distribution<NodeID> dist(0, num_nodes - 1);
    
    constexpr int NUM_ROUTES = 500;
    std::vector<RouteTask> tasks;
    for (int i = 0; i < NUM_ROUTES; ++i) {
        tasks.push_back({dist(gen), dist(gen)});
    }

    std::cout << std::format("\n🚀 STARTING GRAND FINALE INTEGRATION BENCHMARK ({} routes)\n", NUM_ROUTES);
    if (!landmarks) std::cout << "⚠️ WARNING: Landmarks NOT found. ALT will run as Dijkstra.\n";

    std::vector<RoutingResult> baseline_res;
    auto baseline_bench = RunTestProtected<TdAltRouter, router::PriorityQueue>("Baseline (ALT Std 4-Ary)", tasks, view, num_nodes, landmarks);
    if (!baseline_bench.crashed && !baseline_bench.failed) {
        TdAltRouter<router::PriorityQueue> bl_router(view, num_nodes);
        if (landmarks) bl_router.get_heuristic().set_landmarks((const EdgeWeight*)landmarks);
        for(const auto& t : tasks) baseline_res.push_back(bl_router.Route<false, true>(t.source, t.target));
    }

    std::vector<BenchResult> results;
    results.push_back(baseline_bench);
    const RoutingResult* bl_ptr = baseline_res.empty() ? nullptr : baseline_res.data();

    // 1. ALT (Weighted A*) Heaps
    results.push_back(RunTestProtected<TdAltRouter, Strict4AryHeap>("ALT Strict 4-Ary", tasks, view, num_nodes, landmarks, bl_ptr));
    results.push_back(RunTestProtected<TdAltRouter, Strict8ArySoALazyHeap>("ALT Strict 8-Ary SoA Lazy", tasks, view, num_nodes, landmarks, bl_ptr));
    results.push_back(RunTestProtected<TdAltRouter, Strict8ArySoAEagerHeap>("ALT Strict 8-Ary SoA Eager", tasks, view, num_nodes, landmarks, bl_ptr));
    results.push_back(RunTestProtected<TdAltRouter, DeltaQueue>("ALT DeltaQueue", tasks, view, num_nodes, landmarks, bl_ptr));

    // 2. Dijkstra (Monotonic) Heaps
    results.push_back(RunTestProtected<DijkstraRouter, SafeRadixHeap>("DIJKSTRA Radix Heap", tasks, view, num_nodes, nullptr, bl_ptr));
    // results.push_back(RunTestProtected<DijkstraRouter, DeltaBucketQueue<4>>("DIJKSTRA Delta (D=16)", tasks, view, num_nodes, nullptr, bl_ptr));

    std::cout << "\n+------------------------+------------+------------+------------+----------+----------+----------+\n";
    std::cout << "| PQ Type                | Total ms   | ns/Iter    | I-AVG      | QPS      | CORR%    | STATUS   |\n";
    std::cout << "+------------------------+------------+------------+------------+----------+----------+----------+\n";
    for (const auto& r : results) {
        std::string status = r.crashed ? "CRASHED" : (r.failed ? "FAILED" : "OK");
        std::cout << std::format("| {:<22} | {:>10.1f} | {:>10.1f} | {:>10.0f} | {:>8.1f} | {:>7.1f}% | {:>8} |\n",
            r.name, r.total_ms, r.avg_ns_per_iter, r.avg_iters, r.qps, r.correctness, status);
    }
    std::cout << "+------------------------+------------+------------+------------+----------+----------+----------+\n";

    return 0;
}
