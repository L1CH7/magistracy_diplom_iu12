#pragma once

#include <vector>
#include <span>
#include <cstdint>

#include "common/graph_types.hpp"

namespace traffic::data_provider
{

/**
 * @brief Global flat buffer for agent routes.
 * Avoids individual std::vector allocations per agent to maximize cache locality.
 */
struct RouteArena
{
    struct Span
    {
        uint32_t offset;
        uint16_t length;
        uint16_t capacity;
    };

    std::vector< traffic::EdgeID > flat_edges;
    std::vector< uint32_t > flat_etas_sec; // Parallel to flat_edges
    std::vector< Span > agent_spans;       // Index = AgentID

    /**
     * @brief Retrieves a read-only view of an agent's current route.
     * @param agent_id Unique identifier of the agent.
     * @return std::span of EdgeIDs.
     */
    [[nodiscard]] std::span< const traffic::EdgeID > GetRoute( uint32_t agent_id ) const
    {
        if( agent_id >= agent_spans.size() )
        {
            return {};
        }

        const Span & span = agent_spans[ agent_id ];
        return { flat_edges.data() + span.offset, span.length };
    }

    /**
     * @brief Retrieves a read-only view of an agent's planned arrival times (ETAs).
     * @param agent_id Unique identifier of the agent.
     * @return std::span of arrival times in seconds.
     */
    [[nodiscard]] std::span< const uint32_t > GetEtas( uint32_t agent_id ) const
    {
        if( agent_id >= agent_spans.size() )
        {
            return {};
        }

        const Span & span = agent_spans[ agent_id ];
        return { flat_etas_sec.data() + span.offset, span.length };
    }

    /**
     * @brief Updates or allocates a new route for an agent with its ETAs.
     * If the new route exceeds the current span's length, it is appended to both flat buffers.
     * @param agent_id Unique identifier of the agent.
     * @param new_path New sequence of edges for the agent.
     * @param new_etas Planned arrival times for each edge in the sequence.
     */
    void UpdateRoute( uint32_t agent_id, 
                      std::span< const traffic::EdgeID > new_path,
                      std::span< const uint32_t > new_etas )
    {
        if( agent_id >= agent_spans.size() )
        {
            agent_spans.resize( agent_id + 1, { 0, 0, 0 } );
        }

        Span & span = agent_spans[ agent_id ];

        // If new path fits in existing span capacity, just overwrite to maintain locality
        if( new_path.size() <= span.capacity )
        {
            std::copy( new_path.begin(), new_path.end(), flat_edges.begin() + span.offset );
            std::copy( new_etas.begin(), new_etas.end(), flat_etas_sec.begin() + span.offset );
            span.length = static_cast< uint16_t >( new_path.size() );
        }
        else
        {
            // Allocate at the end of the flat buffers to ensure contiguous storage for the agent
            span.offset = static_cast< uint32_t >( flat_edges.size() );
            span.capacity = static_cast< uint16_t >( new_path.size() );
            span.length = static_cast< uint16_t >( new_path.size() );
            
            flat_edges.insert( flat_edges.end(), new_path.begin(), new_path.end() );
            flat_etas_sec.insert( flat_etas_sec.end(), new_etas.begin(), new_etas.end() );
        }
    }
};

} // namespace traffic::data_provider
