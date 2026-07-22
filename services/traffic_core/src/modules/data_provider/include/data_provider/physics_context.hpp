#pragma once

#include <atomic>
#include <cstdint>
#include <vector>

#include "common/graph_types.hpp"

namespace traffic::data_provider
{

/**
 * @brief Легковесный контекст вычислений кинематики и физики заторов.
 * Все указатели являются невладеющими.
 */
struct PhysicsContext
{
    // Live physical occupancy data (updated during transitions)
    uint32_t * live_volumes = nullptr;
    uint32_t * max_volumes = nullptr;
    std::atomic< uint32_t > * queue_volumes = nullptr;
    const traffic::PenaltyScale * k_magic = nullptr;

    // Static edge weights from the CSR graph (w_i = free-flow travel time in seconds).
    const traffic::EdgeWeight * static_weights = nullptr;

    // Precomputed per-edge physical lengths in meters, indexed by EdgeID.
    const float * edge_lengths_m = nullptr;

    // Pointer to mmap'd ExtendedAttributes array
    const ExtendedAttributes * edge_attributes = nullptr;

    uint32_t current_time_sec = 0;
    uint16_t asf = 1;
    std::vector< uint32_t > * completed_agents_out = nullptr;

    // Параметры подсистемы противодействия заторам и дедлокам
    bool deadlock_mitigation_enabled = true;
    uint8_t deadlock_mitigation_mode = 0; // 0: sumo_virtual_buffer, 1: cs_despawn_target, 2: cs_despawn_home
    float time_to_teleport_sec = 300.0f;
    float min_virtual_speed_mps = 2.0f;
    uint64_t * teleported_jam_count_out = nullptr;
};

} // namespace traffic::data_provider
