#pragma once
#include <immintrin.h>
#include <cstdint>
#include <algorithm>
#include "common/graph_types.hpp"

namespace traffic::router {

class ALTHeuristic {
public:
    // Функция ожидает ровно 16 лэндмарок (32 элемента uint16_t)
    [[nodiscard]] inline traffic::PathWeight get_heuristic_avx2(
        const uint16_t* __restrict u_ptr, 
        const uint16_t* __restrict t_ptr) const noexcept 
    {
        // 1. Загружаем все 64 байта (16 лэндмарок) в 2 регистра
        __m256i u0 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr));
        __m256i u1 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + 16));
        
        __m256i t0 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr));
        __m256i t1 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr + 16));

        // 2. Вычисляем разницы.
        // Формат: [to_L, from_L, to_L, from_L...]
        // Для четных индексов (to_L):   h = max(0, u - t)  => _mm256_subs_epu16(u, t)
        // Для нечетных индексов (from_L): h = max(0, t - u)  => _mm256_subs_epu16(t, u)
        
        __m256i diff_ut_0 = _mm256_subs_epu16(u0, t0);
        __m256i diff_tu_0 = _mm256_subs_epu16(t0, u0);
        // Blend берет четные элементы из первого аргумента (0, 2, 4...), нечетные из второго (1, 3...)
        // Маска 0xAA (10101010) выбирает элементы 1, 3, 5, 7, 9, 11, 13, 15 из второго операнда
        __m256i h0 = _mm256_blend_epi16(diff_ut_0, diff_tu_0, 0xAA);

        __m256i diff_ut_1 = _mm256_subs_epu16(u1, t1);
        __m256i diff_tu_1 = _mm256_subs_epu16(t1, u1);
        __m256i h1 = _mm256_blend_epi16(diff_ut_1, diff_tu_1, 0xAA);

        // 3. Находим максимум между двумя половинами (h0 и h1)
        __m256i max_h = _mm256_max_epu16(h0, h1);

        // 4. Горизонтальный максимум внутри вектора (из 16 значений выбираем одно)
        // a. Складываем пополам (256 -> 128)
        __m128i max128 = _mm_max_epu16(
            _mm256_castsi256_si128(max_h), 
            _mm256_extracti128_si256(max_h, 1)
        );
        // b. Складываем 128 -> 64
        max128 = _mm_max_epu16(max128, _mm_shuffle_epi32(max128, _MM_SHUFFLE(1, 0, 3, 2)));
        // c. Складываем 64 -> 32
        max128 = _mm_max_epu16(max128, _mm_shufflelo_epi16(max128, _MM_SHUFFLE(1, 0, 3, 2)));
        // d. Складываем 32 -> 16
        max128 = _mm_max_epu16(max128, _mm_shufflelo_epi16(max128, _MM_SHUFFLE(2, 3, 0, 1)));

        return static_cast<traffic::PathWeight>(_mm_extract_epi16(max128, 0));
    }
};

} // namespace traffic::router

