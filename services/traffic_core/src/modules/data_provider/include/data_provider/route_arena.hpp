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
    };

    std::vector< traffic::EdgeID > flat_edges;
    std::vector< Span > agent_spans; // Index = AgentID

    /**
     * @brief Retrieves a read-only view of an agent's route.
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
     * @brief Updates or allocates a new route for an agent.
     * If the new route exceeds the current span's length, it is appended to the flat_edges buffer.
     * @param agent_id Unique identifier of the agent.
     * @param new_path New sequence of edges for the agent.
     */
    void UpdateRoute( uint32_t agent_id, std::span< const traffic::EdgeID > new_path )
    {
        if( agent_id >= agent_spans.size() )
        {
            agent_spans.resize( agent_id + 1, { 0, 0 } );
        }

        Span & span = agent_spans[ agent_id ];

        // If new path fits in existing span, just overwrite (optimistic path)
        if( new_path.size() <= span.length )
        {
            std::copy( new_path.begin(), new_path.end(), flat_edges.begin() + span.offset );
            span.length = static_cast< uint16_t >( new_path.size() );
        }
        else
        {
            // Allocate at the end of the flat buffer
            span.offset = static_cast< uint32_t >( flat_edges.size() );
            span.length = static_cast< uint16_t >( new_path.size() );
            
            flat_edges.insert( flat_edges.end(), new_path.begin(), new_path.end() );
        }
    }
};

} // namespace traffic::data_provider
