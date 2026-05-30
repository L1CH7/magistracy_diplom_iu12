#include <iostream>
#include <fstream>
#include <chrono>
#include <vector>
#include <thread>
#include <mutex>
#include <random>
#include <filesystem>
#include <format>
#include <pthread.h>
#include <sched.h>

#include "router/control/router_manager.hpp"
#include "router/compute/td_alt_router.hpp"
#include "router/compute/advanced_pqs.hpp"

using namespace traffic;
using namespace traffic::router::compute;

struct RouteTask {
    NodeID source;
    NodeID target;
};

// Worker configuration
struct WorkerResult {
    double duration_ms = 0.0;
    uint64_t completed_tasks = 0;
};

// Global landmarks pointer helper
const uint16_t* g_landmarks = nullptr;

// Thread body: processes a slice of tasks using a thread-local Router instance
void RoutingWorker(
    int thread_id,
    GraphView view,
    NodeID num_nodes,
    const std::vector<RouteTask>& task_slice,
    WorkerResult& result
) {
    // Thread-local Router instance to guarantee zero data sharing/contention in memory
    using RouterT = TdAltRouter<Strict4AryHeap>;
    RouterT router_instance(view, num_nodes);

    if (g_landmarks) {
        router_instance.get_heuristic().set_landmarks(reinterpret_cast<const EdgeWeight*>(g_landmarks));
    }

    auto start_time = std::chrono::high_resolution_clock::now();

    for (const auto& task : task_slice) {
        auto route_res = router_instance.template Route<false, false>(task.source, task.target);
        result.completed_tasks++;
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    result.duration_ms = std::chrono::duration<double, std::milli>(end_time - start_time).count();
}

int main(int argc, char** argv) {
    std::string data_path = "/app/data";
    std::string out_csv = "/app/benchmarks/traffic-core/stats/multithreading_results.csv";

    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--data" && i + 1 < argc) {
            data_path = argv[i+1];
        }
        if (std::string(argv[i]) == "--out" && i + 1 < argc) {
            out_csv = argv[i+1];
        }
    }

    router::control::RouterManager manager;
    if (!manager.LoadGraphs(data_path)) {
        std::cerr << "Failed to load graphs from " << data_path << "\n";
        return 1;
    }

    auto view = manager.get_view();
    auto num_nodes = manager.num_nodes();
    g_landmarks = manager.get_landmarks_ptr();

    if (!g_landmarks) {
        std::cerr << "⚠️ Warning: Landmarks are NOT loaded! ALT will fallback to A-Star/Dijkstra.\n";
    }

    // Generate stable 2000 multi-thread queries (larger pool to reduce noise in high thread counts)
    std::mt19937 gen(42);
    std::uniform_int_distribution<NodeID> dist(0, num_nodes - 1);
    constexpr int TOTAL_TASKS = 2000;
    std::vector<RouteTask> tasks;
    for (int i = 0; i < TOTAL_TASKS; ++i) {
        tasks.push_back({dist(gen), dist(gen)});
    }

    // Warm-up to ensure L3/RAM cache stability
    std::cout << "🔥 Warming up caches... " << std::flush;
    {
        WorkerResult dummy_res;
        std::vector<RouteTask> warmup_tasks(tasks.begin(), tasks.begin() + 200);
        RoutingWorker(0, view, num_nodes, warmup_tasks, dummy_res);
    }
    std::cout << "Ready!\n\n";

    unsigned hw_threads = std::thread::hardware_concurrency();
    unsigned phys_cores = hw_threads > 1 ? hw_threads / 2 : 1;

    std::cout << std::format("💻 Detected System Hardware Topology:\n");
    std::cout << std::format("   - Total Logical Cores (SMT): {}\n", hw_threads);
    std::cout << std::format("   - Total Physical Cores (No-SMT): {}\n\n", phys_cores);

    // Output target setup
    std::filesystem::create_directories(std::filesystem::path(out_csv).parent_path());
    std::ofstream csv(out_csv);
    csv << "ThreadCount,Mode,RPS,Speedup\n";

    // Store 1-thread baselines for Speedup calculation
    double base_rps_no_affinity = 1.0;
    double base_rps_smt = 1.0;
    double base_rps_nosmt = 1.0;

    std::cout << "🚀 STARTING MULTI-THREAD SCALABILITY SCENARIO (ALT + 4-ary)\n";
    std::cout << "===============================================================\n";

    // 0 = No-Affinity, 1 = SMT-Affinity, 2 = No-SMT-Affinity (Strict Core)
    for (int mode : {0, 1, 2}) {
        std::string mode_str = "";
        std::vector<int> thread_counts;
        
        if (mode == 0) {
            mode_str = "No-Affinity";
            thread_counts.push_back(1);
            for (unsigned t = 2; t <= hw_threads; t += 2) {
                thread_counts.push_back(t);
            }
        }
        else if (mode == 1) {
            mode_str = "SMT-Affinity";
            thread_counts.push_back(1);
            for (unsigned t = 2; t <= hw_threads; t += 2) {
                thread_counts.push_back(t);
            }
        }
        else {
            mode_str = "No-SMT-Affinity";
            thread_counts.push_back(1);
            for (unsigned t = 2; t <= phys_cores; t += 2) {
                thread_counts.push_back(t);
            }
        }

        std::cout << std::format("\n--- Running Mode: {} ---\n", mode_str);

        for (int t_count : thread_counts) {
            std::vector<std::thread> workers;
            std::vector<WorkerResult> worker_results(t_count);
            workers.reserve(t_count);

            // Split workload equally among threads
            int tasks_per_thread = TOTAL_TASKS / t_count;
            
            auto global_start = std::chrono::high_resolution_clock::now();

            for (int i = 0; i < t_count; ++i) {
                int start_idx = i * tasks_per_thread;
                int end_idx = (i == t_count - 1) ? TOTAL_TASKS : (i + 1) * tasks_per_thread;
                
                std::vector<RouteTask> slice(tasks.begin() + start_idx, tasks.begin() + end_idx);

                workers.emplace_back(
                    RoutingWorker, i, view, num_nodes, slice, std::ref(worker_results[i])
                );

                // Set hard affinity safely based on hardware topology
                if (mode == 1 || mode == 2) {
                    unsigned core_id = 0;
                    if (mode == 1) {
                        core_id = i % hw_threads; // SMT: Map to all logical CPUs
                    } else {
                        core_id = i % phys_cores; // No-SMT: Strict 1-to-1 physical core mapping
                    }

                    cpu_set_t cpuset;
                    CPU_ZERO(&cpuset);
                    CPU_SET(core_id, &cpuset);
                    int rc = pthread_setaffinity_np(workers.back().native_handle(), sizeof(cpu_set_t), &cpuset);
                    if (rc != 0) {
                        std::cerr << std::format("  [Error] Failed to set affinity for thread {} on CPU {}\n", i, core_id);
                    }
                }
            }

            // Await workers
            for (auto& th : workers) {
                if (th.joinable()) th.join();
            }

            auto global_end = std::chrono::high_resolution_clock::now();
            double elapsed_ms = std::chrono::duration<double, std::milli>(global_end - global_start).count();
            
            // Metrics calculation
            double rps = (static_cast<double>(TOTAL_TASKS) / elapsed_ms) * 1000.0;
            
            if (t_count == 1) {
                if (mode == 0) base_rps_no_affinity = rps;
                else if (mode == 1) base_rps_smt = rps;
                else base_rps_nosmt = rps;
            }

            double base_rps = base_rps_no_affinity;
            if (mode == 1) base_rps = base_rps_smt;
            else if (mode == 2) base_rps = base_rps_nosmt;

            double speedup = rps / base_rps;

            std::cout << std::format("  Threads: {:2d} | RPS: {:8.2f} | Speedup: {:5.2f}x\n", t_count, rps, speedup);
            csv << std::format("{},{},{:.2f},{:.2f}\n", t_count, mode_str, rps, speedup);
        }
    }

    csv.close();
    std::cout << std::format("\n🎉 SCALABILITY BENCHMARK COMPLETE! Written to: {}\n", out_csv);
    return 0;
}
