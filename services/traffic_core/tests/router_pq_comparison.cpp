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
    std::string error_msg = "";
};

template<typename PQType>
BenchResult RunTestProtected(const std::string& name, 
                             const std::vector<RouteTask>& tasks,
                             GraphView view, 
                             NodeID num_nodes,
                             const EdgeWeight* landmarks,
                             const RoutingResult* baseline_results = nullptr) 
{
    std::cout << "  - Starting test: " << name << "... " << std::flush;
    
    BenchResult res;
    res.name = name;
    
    int sig = sigsetjmp(g_jump_buffer, 1);
    if (sig == 0) {
        g_current_route_idx = 0;
        {
            TestGuard guard; // Sets g_test_in_progress = 1
            try {
                TdAltRouter<PQType> router_instance(view, num_nodes);
                if (landmarks) router_instance.get_heuristic().set_landmarks(landmarks);

                uint64_t total_iters = 0;
                uint32_t correct_count = 0;
                
                auto start = std::chrono::high_resolution_clock::now();
                for (size_t i = 0; i < tasks.size(); ++i) {
                    g_current_route_idx = i;
                    auto route_res = router_instance.template Route<false, true>(tasks[i].source, tasks[i].target);
                    
                    total_iters += route_res.visited_nodes_count;
                    if (baseline_results && route_res.total_weight == baseline_results[i].total_weight) {
                        correct_count++;
                    } else if (!baseline_results) {
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
                res.error_msg = e.what();
                std::cout << "FAILED: " << e.what() << "\n";
            }
            // router_instance destructor is called here, while guard is still alive!
        }
    } else {
        res.crashed = true;
        res.failed = true;
        res.error_msg = std::format("CRASHED (Signal {}) at route {}", sig, (int)g_current_route_idx);
        std::cout << " !!! CRASHED !!! at route " << g_current_route_idx << "\n";
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
        return 1;
    }

    auto view = manager.get_view();
    auto num_nodes = manager.num_nodes();
    
    std::mt19937 gen(42);
    std::uniform_int_distribution<NodeID> dist(0, num_nodes - 1);
    
    constexpr int NUM_ROUTES = 500;
    std::vector<RouteTask> tasks;
    for (int i = 0; i < NUM_ROUTES; ++i) {
        tasks.push_back({dist(gen), dist(gen)});
    }

    std::cout << std::format("\n🚀 STARTING RESILIENT INTEGRATION BENCHMARK ({} routes)\n", NUM_ROUTES);

    std::vector<RoutingResult> baseline_res;
    auto baseline_bench = RunTestProtected<router::PriorityQueue>("Baseline (Std 4-Ary)", tasks, view, num_nodes, nullptr);
    if (baseline_bench.crashed || baseline_bench.failed) {
        std::cerr << "FATAL: Baseline failed. Correctness metrics will be disabled.\n";
    } else {
        TdAltRouter<router::PriorityQueue> bl_router(view, num_nodes);
        for(const auto& t : tasks) baseline_res.push_back(bl_router.Route<false, true>(t.source, t.target));
    }

    std::vector<BenchResult> results;
    results.push_back(baseline_bench);
    const RoutingResult* bl_ptr = baseline_res.empty() ? nullptr : baseline_res.data();

    results.push_back(RunTestProtected<Ultimate4AryHeap>("Ultimate 4-Ary", tasks, view, num_nodes, nullptr, bl_ptr));
    results.push_back(RunTestProtected<Ultimate8ArySoAHeap>("Ultimate 8-Ary (SoA)", tasks, view, num_nodes, nullptr, bl_ptr));
    results.push_back(RunTestProtected<SafeRadixHeap>("Safe Vector Radix", tasks, view, num_nodes, nullptr, bl_ptr));
    results.push_back(RunTestProtected<DeltaBucketQueue<2>>("Delta Bucket (D=4)", tasks, view, num_nodes, nullptr, bl_ptr));
    results.push_back(RunTestProtected<DeltaBucketQueue<3>>("Delta Bucket (D=8)", tasks, view, num_nodes, nullptr, bl_ptr));
    results.push_back(RunTestProtected<DeltaBucketQueue<4>>("Delta Bucket (D=16)", tasks, view, num_nodes, nullptr, bl_ptr));

    std::cout << "\n+------------------------+------------+------------+------------+----------+----------+----------+\n";
    std::cout << "| PQ Type                | Total ms   | ns/Iter    | I-AVG      | QPS      | CORR%    | STATUS   |\n";
    std::cout << "+------------------------+------------+------------+------------+----------+----------+----------+\n";
    for (const auto& r : results) {
        std::string status = r.crashed ? "CRASHED" : (r.failed ? "FAILED" : "OK");
        if (r.crashed) status += "@" + std::to_string(r.completed_routes);

        std::cout << std::format("| {:<22} | {:>10.1f} | {:>10.1f} | {:>10.0f} | {:>8.1f} | {:>7.1f}% | {:>8} |\n",
            r.name, r.total_ms, r.avg_ns_per_iter, r.avg_iters, r.qps, r.correctness, status);
    }
    std::cout << "+------------------------+------------+------------+------------+----------+----------+----------+\n";

    return 0;
}
