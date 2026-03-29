#pragma once
#include <immintrin.h>
#include <cstdint>
#include <algorithm>
#include "common/graph_types.hpp"

namespace traffic::router {

class ALTHeuristic {
public:
    // Функция теперь принимает готовые регистры t0 и t1 по значению!
    [[nodiscard]] inline traffic::PathWeight get_heuristic_avx2(
        const uint16_t* __restrict u_ptr, 
        const __m256i t0, 
        const __m256i t1) const noexcept 
    {
        // Грузим только текущий узел (32 байта за раз)
        __m256i u0 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr));
        __m256i u1 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + 16));

        // Вычисляем разницы
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

        // Горизонтальный максимум
        __m128i max128 = _mm_max_epu16(_mm256_castsi256_si128(max_h), _mm256_extracti128_si256(max_h, 1));
        max128 = _mm_max_epu16(max128, _mm_shuffle_epi32(max128, _MM_SHUFFLE(1, 0, 3, 2)));
        // c. Складываем 64 -> 32
        max128 = _mm_max_epu16(max128, _mm_shufflelo_epi16(max128, _MM_SHUFFLE(1, 0, 3, 2)));
        // d. Складываем 32 -> 16
        max128 = _mm_max_epu16(max128, _mm_shufflelo_epi16(max128, _MM_SHUFFLE(2, 3, 0, 1)));

        return static_cast<traffic::PathWeight>(_mm_extract_epi16(max128, 0));
    }
};

} // namespace traffic::router

