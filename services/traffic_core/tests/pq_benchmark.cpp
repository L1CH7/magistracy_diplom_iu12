#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include "doctest.h"
#include <iostream>
#include <vector>
#include <chrono>
#include <random>
#include <iomanip>
#include <print>
#include <x86intrin.h>
#include "router/compute/priority_queue.hpp"
#include "router/compute/advanced_pqs.hpp"

using namespace traffic::router::compute;

struct BenchResult {
    std::string name;
    double total_ms;
    double cycles_per_op;
    uint64_t chaos_factor; // Метрика деградации порядка (меньше - лучше)
};

void warm_up() {
    volatile uint64_t sum = 0;
    for (int i = 0; i < 1'000'000; ++i) sum += i;
}

template<typename PQ>
BenchResult run_wa_bench(const std::string& name, size_t num_ops) {
    PQ pq;
    std::mt19937 gen(42);
    std::uniform_int_distribution<uint32_t> dist_forward(1, 300);
    std::uniform_int_distribution<uint32_t> dist_backward(1, 150);
    std::uniform_int_distribution<uint32_t> dist_prob(1, 100);
    
    if constexpr (requires(PQ p) { p.reserve(100); }) { pq.reserve(num_ops); }

    int32_t current_f = 1000;
    uint32_t max_f_seen = 1000;
    uint64_t chaos_factor = 0;
    volatile uint32_t sink = 0;

    auto start_time = std::chrono::high_resolution_clock::now();
    uint64_t start_cycles = __rdtsc();

    for (size_t i = 0; i < num_ops; ++i) {
        if (pq.empty() || dist_prob(gen) > 40) {
            int32_t new_f = current_f;
            if (dist_prob(gen) > 15) {
                new_f += dist_forward(gen); 
            } else {
                new_f -= dist_backward(gen); // WA* немонотонность
                if (new_f < 0) new_f = 0;
            }
            pq.push({static_cast<traffic::PathWeight>(new_f), static_cast<traffic::NodeID>(i)});
        } else {
            auto top = pq.pop();
            current_f = top.weight;
            sink = top.id;
            
            if (current_f < max_f_seen) {
                chaos_factor += (max_f_seen - current_f);
            } else {
                max_f_seen = current_f;
            }
        }
    }

    uint64_t end_cycles = __rdtsc();
    auto end_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> diff = end_time - start_time;
    uint64_t delta_cycles = (end_cycles > start_cycles) ? (end_cycles - start_cycles) : 0;

    return {name, diff.count(), static_cast<double>(delta_cycles) / num_ops, chaos_factor};
}

TEST_CASE("Weighted A* PQ Benchmark") {
    const size_t NUM_OPERATIONS = 10'000'000;
    std::vector<BenchResult> results;

    std::println("TIP: Run with 'taskset -c 0 ./pq_benchmark' for stable results");
    std::cout << "\n🚀 STARTING RELAXED WA* BENCHMARK (" << NUM_OPERATIONS << " ops)\n";
    
    warm_up(); results.push_back(run_wa_bench<traffic::router::PriorityQueue>("Std 4-Ary (Baseline)", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<Branchless4AryHeap>("Branchless 4-Ary", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<SoA8AryAvx2Heap>("SoA 8-Ary AVX2", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<Ultimate4AryHeap>("Ultimate 4-Ary v2", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<Ultimate8ArySoAHeap>("Ultimate 8-Ary v2", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<SafeRadixHeap>("Safe Vector Radix", NUM_OPERATIONS));
    warm_up(); results.push_back(run_wa_bench<DeltaBucketQueue<4>>("Delta-Stepping (D=16)", NUM_OPERATIONS));

    std::cout << "\n+------------------------+------------+------------+--------------+\n";
    std::cout << "| Search Structure       | Latency ms | Cycles/Op  | Chaos Factor |\n";
    std::cout << "+------------------------+------------+------------+--------------+\n";
    for (const auto& res : results) {
        std::cout << "| " << std::left << std::setw(22) << res.name 
                  << " | " << std::right << std::setw(10) << std::fixed << std::setprecision(2) << res.total_ms
                  << " | " << std::right << std::setw(10) << std::fixed << std::setprecision(1) << res.cycles_per_op 
                  << " | " << std::right << std::setw(12) << res.chaos_factor << " |\n";
    }
    std::cout << "+------------------------+------------+------------+--------------+\n";
}
