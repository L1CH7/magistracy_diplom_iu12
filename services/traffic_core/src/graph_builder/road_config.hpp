#pragma once

#include <cstdint>
#include <string_view>

// ============================================================================
// ROAD CONFIGURATION TABLE
// ============================================================================
// Использование: при заполнении атрибутов графа, вычислении t_free и штрафов.
//
// speed_tolerance_kmh: добавка к официальному лимиту в км/ч.
//   В России (и большинстве стран Европы): +19 км/ч до начала штрафа.
//   Т.е. при расчёте t_free мы используем EFFECTIVE_SPEED = posted_speed + 19.
//   Это приближает расчётное время к реальному времени в пробке без нагрузки.
//
// turn_right_sec / turn_left_sec / turn_uturn_sec:
//   Штрафы за манёвр в секундах. Добавляются к base_time рёбра Edge-based графа.
//   Для развороток на магистралях и т.п. - ставим IMPASSABLE (999).
//
// IMPASSABLE = запрещено, ребро в CSR не создаётся.
// ============================================================================

namespace traffic::graph_builder
{

constexpr int32_t TURN_IMPASSABLE = 999;

// Оговорённая допустимая прибавка скорости (ненаказываемый предел)
constexpr float SPEED_TOLERANCE_KMH = 19.0f;

struct RoadTypeConfig
{
    std::string_view highway_type;
    float            default_speed_kmh;
    int              default_lanes;
    // Штрафы за поворот в секундах (для Edge-based Line Graph трансформации)
    int32_t          turn_right_sec;     // правый поворот
    int32_t          turn_straight_sec;  // прямо (обычно 0)
    int32_t          turn_left_sec;      // левый (через встречку) поворот
    int32_t          turn_uturn_sec;     // разворот
};

// Порядок важен: поиск ведётся линейно по первому совпадению.
// Должны перечисляться от более специфичных к более общим.
constexpr RoadTypeConfig ROAD_TYPE_CONFIGS[] = {
    // highway_type         spd   lanes  right  str  left  uturn
    { "motorway",           110,  2,     0,     0,   TURN_IMPASSABLE, TURN_IMPASSABLE },
    { "motorway_link",      80,   1,     0,     0,   5,    TURN_IMPASSABLE },
    { "trunk",              90,   2,     0,     0,   5,    TURN_IMPASSABLE },
    { "trunk_link",         70,   1,     0,     0,   5,    TURN_IMPASSABLE },
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
