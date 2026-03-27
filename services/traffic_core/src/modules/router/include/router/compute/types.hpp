#pragma once

#include <cstdint>
#include <limits>
#include <cstddef>

#if defined(__cpp_lib_hardware_interference_size)
    #include <new>
#endif

namespace traffic::router {

// Базовые типы, оптимизированные для работы в кэше и векторных инструкциях
using NodeID = uint32_t;
using EdgeID = uint32_t;
using Weight = uint32_t;
using TimeSec = uint32_t;

// Замкнутый мир: макро-константы ошибок и инвалидаций
constexpr NodeID INVALID_NODE = std::numeric_limits<NodeID>::max();
constexpr EdgeID INVALID_EDGE = std::numeric_limits<EdgeID>::max();
// Половина от uint32_max, чтобы избежать overflow при X + INF_WEIGHT
constexpr Weight INF_WEIGHT   = std::numeric_limits<Weight>::max() / 2; 

// Cache Line Size (для архитектуры AoS с жестким выравниванием 64 байта)
constexpr std::size_t CACHE_LINE_SIZE = 64;

#define ALIGN_CACHE_LINE alignas(CACHE_LINE_SIZE)

} // namespace traffic::router
