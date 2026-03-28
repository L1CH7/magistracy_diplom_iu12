#pragma once

#include <cstdint>
#include <limits>
#include <cstddef>

#if defined(__cpp_lib_hardware_interference_size)
    #include <new>
#endif

// Including from the root-relative path as defined in CMake
#include "common/graph_types.hpp"

namespace traffic::router {

// Базовые типы, оптимизированные для работы в кэше и векторных инструкциях
using NodeID = traffic::NodeID;
using EdgeID = traffic::EdgeID;
using Weight = traffic::PathWeight; // g_score / h_score are 32-bit
using PointCount = traffic::PointCount;
using TimeSec = uint32_t;

// Замкнутый мир: макро-константы ошибок и инвалидаций
constexpr NodeID INVALID_NODE = traffic::INVALID_NODE;
constexpr EdgeID INVALID_EDGE = 0xFFFFFFFF;
// Половина от uint32_max, чтобы избежать overflow при X + INF_WEIGHT
constexpr Weight INF_WEIGHT   = traffic::INF_WEIGHT / 2; 

// Cache Line Size (для архитектуры AoS с жестким выравниванием 64 байта)
constexpr std::size_t CACHE_LINE_SIZE = 64;

#define ALIGN_CACHE_LINE alignas(CACHE_LINE_SIZE)

} // namespace traffic::router
