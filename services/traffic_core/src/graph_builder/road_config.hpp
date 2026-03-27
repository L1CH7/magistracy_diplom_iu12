#pragma once

#include <cstdint>
#include <string_view>
#include <limits>
#include <string>

namespace traffic::graph_builder
{

// Физические константы для кинематических расчетов
constexpr float SPEED_TOLERANCE_KMH = 19.0f; // Нештрафуемый порог
constexpr float CAR_LENGTH_M = 7.0f;         // 5m машина + 2m дистанция
constexpr int32_t K_MAGIC_SHIFT = 1 << 20;   // 2^20 для Fixed-Point math

// Кинематика манёвров
constexpr float ACCEL_MS2 = 1.5f;            // Базовое ускорение (м/с^2)
constexpr float DECEL_MS2 = 2.0f;            // Базовое замедление (м/с^2)
constexpr float MU_FRICTION = 0.6f;          // Коэффициент сцепления (поперечный)
constexpr float G_ACCEL = 9.81f;
constexpr float PI      = 3.14159265f;

constexpr uint32_t TURN_IMPASSABLE = std::numeric_limits<uint32_t>::max();

struct RoadTypeConfig
{
    std::string_view highway_type;
    float            default_speed_kmh;
    int              default_lanes;
    // Дефолтные штрафы за поворот в секундах
    std::int32_t     turn_right_sec;
    std::int32_t     turn_straight_sec;
    std::int32_t     turn_left_sec;
    std::int32_t     turn_uturn_sec;
};

// Порядок важен: поиск ведётся линейно по первому совпадению.
// Должны перечисляться от более специфичных к более общим.
constexpr RoadTypeConfig ROAD_TYPE_CONFIGS[] = {
    // highway_type         spd   lanes  right  str  left  uturn
    { "motorway",           110,  2,     0,     0,   999,  999 },
    { "motorway_link",      80,   1,     0,     0,   5,    999 },
    { "trunk",              90,   2,     0,     0,   5,    999 },
    { "trunk_link",         70,   1,     0,     0,   5,    999 },
    { "primary",            60,   2,     1,     0,   4,    30  },
    { "primary_link",       50,   1,     1,     0,   4,    30  },
    { "secondary",          60,   2,     1,     0,   4,    30  },
    { "secondary_link",     50,   1,     1,     0,   4,    30  },
    { "tertiary",           50,   1,     1,     0,   3,    20  },
    { "tertiary_link",      40,   1,     1,     0,   3,    20  },
    { "residential",        20,   1,     0,     0,   2,    10  },
    { "living_street",      10,   1,     0,     0,   1,    5   },
    { "service",            20,   1,     0,     0,   2,    10  },
    { "unclassified",       30,   1,     0,     0,   2,    15  },
    // Fallback (должен быть последним)
    { "",                   30,   1,     1,     0,   3,    20  },
};

constexpr size_t ROAD_TYPE_COUNT = sizeof( ROAD_TYPE_CONFIGS ) / sizeof( ROAD_TYPE_CONFIGS[ 0 ] );

// Возвращает конфиг по типу дороги. При отсутствии — возвращает fallback.
inline const RoadTypeConfig & GetRoadConfig( std::string_view highway_type )
{
    for( size_t i = 0; i < ROAD_TYPE_COUNT - 1; ++i )
    {
        if( ROAD_TYPE_CONFIGS[ i ].highway_type == highway_type )
            return ROAD_TYPE_CONFIGS[ i ];
    }
    return ROAD_TYPE_CONFIGS[ ROAD_TYPE_COUNT - 1 ]; // fallback
}

// Вычисляет эффективную скорость с учётом ненаказываемого предела.
// posted_speed = оффициальный лимит из OSM (если 0 — используем default для типа).
inline float EffectiveSpeedKmh( float posted_speed, float default_speed )
{
    const float base = ( posted_speed > 0.0f ) ? posted_speed : default_speed;
    return base + SPEED_TOLERANCE_KMH;
}

// Длина (м) → время (сек) при заданной скорости (км/ч)
inline float FreeFLowTimeSec( float length_m, float speed_kmh )
{
    const float speed_ms = speed_kmh / 3.6f;
    return length_m / speed_ms;
}

} // namespace traffic::graph_builder
