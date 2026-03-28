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
        traffic::PointCount n = 0;
        traffic::EdgeID m = 0;
        std::vector<traffic::EdgeID> ptr;
        std::vector<traffic::NodeID> col;
        std::vector<traffic::EdgeWeight> time;
    };

    std::expected<CSR, std::string> LoadCSR( const std::string & path );
    
    std::vector<traffic::PathWeight> RunDijkstra( traffic::NodeID start, const CSR & graph );
    
    // Strategy: Farthest Node (Generates boundary candidates)
    std::vector<traffic::NodeID> GenerateFarthestCandidates( const CSR & graph, int count );
    
    // Strategy: Avoid (Generates candidates in sparse areas)
    std::vector<traffic::NodeID> GenerateAvoidCandidates( const CSR & graph, int count, const std::vector<traffic::NodeID> & existing_pool );

    // Strategy: MaxCover Stochastic Optimization
    std::vector<traffic::NodeID> OptimizeMaxCover( const std::vector<std::vector<traffic::PathWeight>> & to_L,
                                            const std::vector<std::vector<traffic::PathWeight>> & from_L,
                                            traffic::PointCount num_nodes,
                                            int num_landmarks );
};

} // namespace traffic::graph_builder
