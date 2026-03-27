#pragma once
#include <string>
#include <vector>
#include <expected>
#include <cstdint>
#include "common/graph_types.hpp"

namespace traffic::graph_builder
{

/**
 * @brief LandmarkBuilder implements Phase 3: Advanced ALT Landmarks.
 * It uses Border Minmax (Farthest nodes) and MaxCover (Stochastic Search) to select optimal landmarks.
 * Distances are packed into a 16-bit interleaved format [to_L1, from_L1, to_L2, from_L2, ...]
 */
class LandmarkBuilder
{
public:
    std::expected<void, std::string> Build( const std::string & csr_path, 
                                            const std::string & csr_rev_path, 
                                            const std::string & out_path );

private:
    struct CSR 
    {
        uint32_t n = 0;
        uint32_t m = 0;
        std::vector<uint32_t> ptr;
        std::vector<NodeID> col;
        std::vector<uint32_t> time;
    };

    std::expected<CSR, std::string> LoadCSR( const std::string & path );
    
    std::vector<uint32_t> RunDijkstra( uint32_t start, const CSR & graph );
    
    // Strategy: Farthest Node (Generates boundary candidates)
    std::vector<uint32_t> GenerateFarthestCandidates( const CSR & graph, int count );
    
    // Strategy: Avoid (Generates candidates in sparse areas)
    std::vector<uint32_t> GenerateAvoidCandidates( const CSR & graph, int count, const std::vector<uint32_t> & existing_pool );

    // Strategy: MaxCover Stochastic Optimization
    std::vector<uint32_t> OptimizeMaxCover( const std::vector<std::vector<uint32_t>> & to_L,
                                            const std::vector<std::vector<uint32_t>> & from_L,
                                            uint32_t num_nodes,
                                            int num_landmarks );
};

} // namespace traffic::graph_builder
