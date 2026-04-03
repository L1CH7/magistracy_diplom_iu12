#pragma once

#include <vector>
#include <cstdint>
#include <array>

#include "common/graph_types.hpp"

namespace traffic::common::net
{

static constexpr uint32_t MAX_ROUTE_PATH = 128;

/**
 * @brief Zero-overhead request for path computation.
 */
struct RouteRequest
{
    uint32_t agent_id;
    traffic::EdgeID start_edge;
    traffic::EdgeID target_edge;
    uint16_t asf;                // Availability Search Factor
    uint32_t current_time_sec;
};

/**
 * @brief Response from Router containing computed path and projected arrival times (ETAs).
 * Must be Trivially Copyable for high-performance memcpy-based transport.
 */
struct RouteResponse
{
    uint32_t agent_id;
    uint16_t path_len;
    bool success;

    std::array< traffic::EdgeID, MAX_ROUTE_PATH > path;
    std::array< uint32_t, MAX_ROUTE_PATH > edge_etas_sec;
};

} // namespace traffic::common::net
