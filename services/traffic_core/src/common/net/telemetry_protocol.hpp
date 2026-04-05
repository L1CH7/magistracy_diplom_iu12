#pragma once

#include <cstdint>
#include <array>

#include "common/graph_types.hpp"

namespace traffic::common::net
{

#pragma pack(push, 1)

/**
 * @brief Opcodes for Command REP/REQ socket.
 */
enum class CommandOpcode : uint8_t
{
    START = 1,
    STOP = 2,
    SET_SPEED = 3,
    SET_RESPAWN = 4,
    ROUTE_ONE_OFF = 5
};

/**
 * @brief Command payload for START, STOP, SET_SPEED.
 * Decouples engine control from external clients.
 */
struct CommandRequest
{
    CommandOpcode opcode;
    uint32_t session_id;
    uint32_t request_id;
    uint32_t num_agents;
    uint16_t asf;
    float acceleration;
    uint8_t reserved;
};

/**
 * @brief Header for One-Off Route Request.
 * Followed by num_waypoints * Point2D (lon, lat).
 */
struct OneOffRouteHeader
{
    uint8_t num_waypoints;
    uint32_t start_time_sec;
};

/**
 * @brief Simple point for coordinates.
 */
struct PointCoord
{
    float lon;
    float lat;
};

/**
 * @brief Response header for ROUTE_ONE_OFF.
 * Multi-frame response: [Header, EdgeIDs, ETAs, PointCounts, GeometryData].
 */
struct OneOffRouteResponseHeader
{
    uint8_t success;
    uint16_t num_edges;
    uint32_t total_points;
    float total_distance_m;
    float total_time_sec;
};

/**
 * @brief Response to CommandRequest.
 */
struct CommandAck
{
    uint8_t success;
    uint8_t engine_state; // 0=IDLE, 1=RUNNING, 2=STOPPED
};

/**
 * @brief Header for periodic Telemetry PUB messages (TelemetryPort: 5556).
 * Followed by an array of AgentState structures.
 */
struct TelemetryHeader
{
    uint32_t tick_id;
    float current_sim_time;
    float current_tps;
    uint32_t num_agents;
};

/**
 * @brief Atomic agent state snapshot for GUI rendering.
 */
struct AgentState
{
    uint32_t agent_id;
    traffic::EdgeID current_edge;
    float pos_meters;
};

/**
 * @brief Notification for discrete simulation events (SPAWN/REROUTE).
 * Sent as separate ZMQ frames.
 */
enum class EventType : uint8_t
{
    SPAWN = 1,
    REROUTE = 2
};

struct EventHeader
{
    EventType type;
    uint32_t agent_id;
    uint16_t payload_len; // Number of EdgeIDs following this header
};

#pragma pack(pop)

} // namespace traffic::common::net
