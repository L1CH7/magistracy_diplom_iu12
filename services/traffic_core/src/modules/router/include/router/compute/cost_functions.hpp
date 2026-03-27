#pragma once

#include "types.hpp"
#include <algorithm>

namespace traffic::router {

// Вспомогательный класс для вычисления стоимости (cost) ребра
// В DoD/Hot-loop мы избегаем плавающей запятой (div/mul floats), 
// заменяя её быстрыми LERP'ами (целочисленными).
class CostCalculator {
public:
    // Расчет динамической стоимости ( Mesoscopic Penalty = K_magic * V^2 >> 20 )
    [[nodiscard]] static inline Weight compute_dynamic_cost(Weight base_time, uint16_t volume, int32_t k_magic) noexcept {
        if (volume == 0) return base_time;
        
        // Penalty = (K_magic * V^2) >> 20
        uint64_t v2 = static_cast<uint64_t>(volume) * volume;
        uint64_t penalty = (static_cast<uint64_t>(k_magic) * v2) >> 20;
        
        // Ограничение штрафа (максимум x10 от базового времени проезда)
        return base_time + static_cast<Weight>(std::min<uint64_t>(penalty, static_cast<uint64_t>(base_time) * 10));
    }
};

} // namespace traffic::router
