#include "landmarks.hpp"
#include <fstream>
#include <print>
#include <queue>
#include <random>
#include <algorithm>
#include <limits>
#include <omp.h>

namespace traffic::graph_builder
{

namespace {
    constexpr uint32_t INF = std::numeric_limits<uint32_t>::max() / 2;
}

std::expected<LandmarkBuilder::CSR, std::string> LandmarkBuilder::LoadCSR(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return std::unexpected("Failed to open " + path);
    CSR graph;
    file.read(reinterpret_cast<char*>(&graph.n), sizeof(graph.n));
    file.read(reinterpret_cast<char*>(&graph.m), sizeof(graph.m));
    graph.ptr.resize(graph.n + 1);
    graph.col.resize(graph.m);
    graph.time.resize(graph.m);
    file.read(reinterpret_cast<char*>(graph.ptr.data()), graph.ptr.size() * sizeof(uint32_t));
    file.read(reinterpret_cast<char*>(graph.col.data()), graph.col.size() * sizeof(uint32_t));
    file.read(reinterpret_cast<char*>(graph.time.data()), graph.time.size() * sizeof(uint32_t));
    return graph;
}

std::vector<uint32_t> LandmarkBuilder::RunDijkstra(uint32_t start, const CSR& graph) {
    std::vector<uint32_t> dist(graph.n, INF);
    using P = std::pair<uint32_t, uint32_t>;
    std::priority_queue<P, std::vector<P>, std::greater<P>> pq;
    
    dist[start] = 0;
    pq.push({0, start});
    
    while (!pq.empty()) {
        auto [d, u] = pq.top(); pq.pop();
        if (d > dist[u]) continue;
        
        for (uint32_t e = graph.ptr[u]; e < graph.ptr[u + 1]; ++e) {
            uint32_t v = graph.col[e];
            uint32_t w = graph.time[e];
            if (dist[u] + w < dist[v]) {
                dist[v] = dist[u] + w;
                pq.push({dist[v], v});
            }
        }
    }
    return dist;
}

std::vector<uint32_t> LandmarkBuilder::GenerateFarthestCandidates(const CSR& graph, int count) {
    std::vector<uint32_t> pool;
    std::vector<uint32_t> min_dist(graph.n, INF);
    uint32_t current = 0; // Start arbitrary
    
    for (int i = 0; i < count; ++i) {
        pool.push_back(current);
        auto dists = RunDijkstra(current, graph);
        
        uint32_t farthest = 0;
        uint32_t max_min = 0;
        for (uint32_t v = 0; v < graph.n; ++v) {
            if (dists[v] < min_dist[v]) min_dist[v] = dists[v];
            if (min_dist[v] > max_min && min_dist[v] != INF) {
                max_min = min_dist[v];
                farthest = v;
            }
        }
        current = farthest;
    }
    return pool;
}

std::vector<uint32_t> LandmarkBuilder::GenerateAvoidCandidates(const CSR& graph, int count, const std::vector<uint32_t>& existing_pool) {
    std::vector<uint32_t> min_dist(graph.n, INF);
    
    for (uint32_t lm : existing_pool) {
        auto dists = RunDijkstra(lm, graph);
        for (uint32_t v = 0; v < graph.n; ++v) {
            if (dists[v] < min_dist[v]) min_dist[v] = dists[v];
        }
    }

    std::vector<uint32_t> pool;
    for (int i = 0; i < count; ++i) {
        uint32_t blind_spot = 0;
        uint32_t max_min = 0;
        for (uint32_t v = 0; v < graph.n; ++v) {
            if (min_dist[v] > max_min && min_dist[v] != INF) {
                max_min = min_dist[v];
                blind_spot = v;
            }
        }
        pool.push_back(blind_spot);
        
        auto dists = RunDijkstra(blind_spot, graph);
        for (uint32_t v = 0; v < graph.n; ++v) {
            if (dists[v] < min_dist[v]) min_dist[v] = dists[v];
        }
    }
    return pool;
}

std::vector<uint32_t> LandmarkBuilder::OptimizeMaxCover(const std::vector<std::vector<uint32_t>>& to_L,
                                                        const std::vector<std::vector<uint32_t>>& from_L,
                                                        uint32_t num_nodes,
                                                        int num_landmarks) {
    std::mt19937 gen(1337);
    std::uniform_int_distribution<uint32_t> dist_node(0, num_nodes - 1);
    struct Pair { uint32_t s, t; };
    std::vector<Pair> eval_pairs(1000);
    for (auto& p : eval_pairs) { p.s = dist_node(gen); p.t = dist_node(gen); }

    std::vector<uint32_t> selected_indices(num_landmarks);
    std::iota(selected_indices.begin(), selected_indices.end(), 0);

    auto calc_fitness = [&](const std::vector<uint32_t>& selection) {
        uint64_t total_heuristic = 0;
        for (const auto& p : eval_pairs) {
            uint32_t max_h = 0;
            for (uint32_t idx : selection) {
                uint32_t d_ug = to_L[idx][p.s];
                uint32_t d_vt = to_L[idx][p.t];
                uint32_t h1 = (d_ug != INF && d_vt != INF && d_ug > d_vt) ? (d_ug - d_vt) : 0;
                
                uint32_t d_lu = from_L[idx][p.s];
                uint32_t d_tv = from_L[idx][p.t];
                uint32_t h2 = (d_lu != INF && d_tv != INF && d_tv > d_lu) ? (d_tv - d_lu) : 0;
                
                max_h = std::max({max_h, h1, h2});
            }
            total_heuristic += max_h;
        }
        return total_heuristic;
    };

    uint64_t best_fitness = calc_fitness(selected_indices);
    
    for (int iter = 0; iter < 500; ++iter) {
        uint32_t swap_in = std::uniform_int_distribution<uint32_t>(0, static_cast<uint32_t>(to_L.size()) - 1)(gen);
        int swap_out_pos = std::uniform_int_distribution<int>(0, num_landmarks - 1)(gen);
        
        if (std::find(selected_indices.begin(), selected_indices.end(), swap_in) != selected_indices.end()) continue;

        std::vector<uint32_t> mutated = selected_indices;
        mutated[swap_out_pos] = swap_in;
        
        uint64_t new_fitness = calc_fitness(mutated);
        if (new_fitness > best_fitness) {
            best_fitness = new_fitness;
            selected_indices = mutated;
        }
    }
    return selected_indices;
}

std::expected<void, std::string> LandmarkBuilder::Build(const std::string& csr_path, const std::string& csr_rev_path, const std::string& out_path) {
    auto fwd_res = LoadCSR(csr_path);
    if (!fwd_res) return std::unexpected("FWD: " + fwd_res.error());
    auto rev_res = LoadCSR(csr_rev_path);
    if (!rev_res) return std::unexpected("REV: " + rev_res.error());

    const auto& fwd = *fwd_res;
    const auto& rev = *rev_res;

    std::println("-> Generating Candidate Pool (128 nodes: Farthest + Avoid)...");
    auto pool = GenerateFarthestCandidates(fwd, 64);
    auto avoid = GenerateAvoidCandidates(fwd, 64, pool);
    pool.insert(pool.end(), avoid.begin(), avoid.end()); // Total 128

    std::println("-> Precomputing 128xN Distance Matrix (OpenMP)...");
    std::vector<std::vector<uint32_t>> to_L(128);
    std::vector<std::vector<uint32_t>> from_L(128);
    
    #pragma omp parallel for
    for (int i = 0; i < 128; ++i) {
        to_L[i] = RunDijkstra(pool[i], rev); // Distance TO landmark
        from_L[i] = RunDijkstra(pool[i], fwd); // Distance FROM landmark
    }

    std::println("-> Running MaxCover Stochastic Search...");
    auto best_indices = OptimizeMaxCover(to_L, from_L, fwd.n, TRAFFIC_TOTAL_LANDMARKS);

    std::println("-> Packing {} Selected Landmarks into SIMD Layout...", TRAFFIC_TOTAL_LANDMARKS);
    std::ofstream l_out(out_path, std::ios::binary);
    if (!l_out) return std::unexpected("Cannot write " + out_path);

    for (uint32_t v = 0; v < fwd.n; ++v) {
        uint16_t row_buffer[TRAFFIC_TOTAL_LANDMARKS * 2];
        for (int i = 0; i < TRAFFIC_TOTAL_LANDMARKS; ++i) {
            uint32_t l_idx = best_indices[i];
            row_buffer[i * 2]     = static_cast<uint16_t>(std::min<uint32_t>(to_L[l_idx][v], 0xFFFE));
            row_buffer[i * 2 + 1] = static_cast<uint16_t>(std::min<uint32_t>(from_L[l_idx][v], 0xFFFE));
        }
        l_out.write(reinterpret_cast<const char*>(row_buffer), sizeof(row_buffer));
    }

    std::println("-> Landmarks compiled successfully.");
    return {};
}

} // namespace traffic::graph_builder
