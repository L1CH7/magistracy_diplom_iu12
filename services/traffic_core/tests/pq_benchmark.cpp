#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include "doctest.h"
#include <iostream>
#include <vector>
#include <chrono>
#include <random>
#include <iomanip>
#include <x86intrin.h>
#include "router/compute/priority_queue.hpp"
#include "router/compute/advanced_pqs.hpp"

using namespace traffic::router::compute;

struct BenchResult {
    std::string name;
    double total_ms;
    double cycles_per_op;
};

// Warm-up to stabilize RDTSC and cache
void warm_up() {
    volatile uint64_t sum = 0;
    for (int i = 0; i < 1'000'000; ++i) sum += i;
}

template<typename PQ>
BenchResult run_bench(const std::string& name, size_t num_ops) {
    PQ pq;
    std::mt19937 gen(42);
    std::uniform_int_distribution<uint32_t> dist(1, 500);
    
    uint32_t current_f = 100;
    volatile uint32_t sink = 0;
    
    // Safety check for reserve
    pq.reserve(num_ops);

    auto start_time = std::chrono::high_resolution_clock::now();
    uint64_t start_cycles = __rdtsc();
    
    for (size_t i = 0; i < num_ops; ++i) {
        bool do_push = true;
        if (pq.size() > 100'000) {
            do_push = (i % 2 == 0);
        } else {
            do_push = (i % 3 != 0); 
        }
        
        if (do_push || pq.empty()) {
            pq.push({current_f + dist(gen), static_cast<traffic::NodeID>(i % 1000000)});
        } else {
            auto el = pq.pop();
            current_f = el.weight;
            sink += el.weight;
        }
    }
    
    while (!pq.empty()) {
        auto el = pq.pop();
        sink += el.weight;
    }

    uint64_t end_cycles = __rdtsc();
    auto end_time = std::chrono::high_resolution_clock::now();
    
    std::chrono::duration<double, std::milli> diff = end_time - start_time;
    uint64_t delta_cycles = (end_cycles > start_cycles) ? (end_cycles - start_cycles) : 0;

    return {
        name,
        diff.count(),
        static_cast<double>(delta_cycles) / num_ops
    };
}

TEST_CASE("PQ Performance Benchmark") {
    constexpr size_t NUM_OPERATIONS = 100'000'000;
    std::vector<BenchResult> results;

    std::cout << "\n🚀 STARTING PQ BENCHMARK (" << NUM_OPERATIONS << " operations)\n";
    
    warm_up();
    results.push_back(run_bench<traffic::router::PriorityQueue>("4-Ary Heap (Current)", NUM_OPERATIONS));
    warm_up();
    results.push_back(run_bench<VectorRadixHeap>("Vector Radix Heap", NUM_OPERATIONS));
    warm_up();
    results.push_back(run_bench<FlatRadixHeap>("Flat Radix Heap", NUM_OPERATIONS));
    warm_up();
    results.push_back(run_bench<Simd8AryHeap>("Simd 8-Ary Heap", NUM_OPERATIONS));

    std::cout << "\n+------------------------+------------+------------+\n";
    std::cout << "| Search Structure       | Latency ms | Cycles/Op  |\n";
    std::cout << "+------------------------+------------+------------+\n";
    
    for (const auto& res : results) {
        std::cout << "| " << std::left << std::setw(22) << res.name 
                  << " | " << std::right << std::setw(10) << std::fixed << std::setprecision(2) << res.total_ms 
                  << " | " << std::right << std::setw(10) << std::fixed << std::setprecision(1) << res.cycles_per_op << " |\n";
    }
    std::cout << "+------------------------+------------+------------+\n\n";
}
