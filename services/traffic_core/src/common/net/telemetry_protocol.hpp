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
    ROUTE_ONE_OFF = 5,
    STEP = 6,
    PAUSE = 7,
    RESUME = 8,
    STATS = 9,             ///< Запрос диагностики движка, ответ — JSON-текст (не бинарный ACK)
    DEBUG_AGENT_SAMPLE = 10 ///< Отладочный снимок N агентов: застрявшие + едущие. Ответ — JSON.
                            ///< Поле num_agents в CommandRequest задаёт запрошенное кол-во образцов.
                            ///< Вызывается ТОЛЬКО по явному HTTP-запросу, не фоново.
};

/**
 * @brief Command payload for START, STOP, SET_SPEED, STEP.
 * Exactly 30 bytes, packed.
 */
struct CommandRequest
{
    uint8_t  opcode;           // 1 byte
    uint32_t session_id;       // 4 bytes (Used as duration)
    uint32_t request_id;       // 4 bytes
    uint32_t num_agents;       // 4 bytes
    uint16_t asf;              // 2 bytes
    float    acceleration;     // 4 bytes
    float    telemetry_fps;    // 4 bytes
    float    chaos_factor;     // 4 bytes
    uint8_t  respawn_enabled;  // 1 byte
    uint8_t  reserved[2];      // 2 bytes
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
    float calc_time_ms;
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
    uint8_t  msg_type = 1;    ///< 1 = agent states, 2 = heatmap volumes
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
 * @brief Header for heatmap volume PUB messages (msg_type=2).
 * Followed by an array of HeatmapEntry.
 * Sent ~1Hz as a separate ZMQ message (not part of the 25Hz agent telemetry).
 */
struct HeatmapHeader
{
    uint8_t  msg_type = 2;
    uint32_t tick_id;
    float    sim_time;
    uint32_t num_entries;   ///< Number of HeatmapEntry records following
};

/**
 * @brief Single edge heatmap record: centroid + current volume.
 * Only non-zero volume edges are included.
 */
struct HeatmapEntry
{
    uint64_t osm_id;    ///< OpenStreetMap Way ID
    uint16_t volume;    ///< Agent count (clamped to 65535)
    uint16_t capacity;  ///< Computed capacity (lanes * speed factor), 0 = unknown
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
