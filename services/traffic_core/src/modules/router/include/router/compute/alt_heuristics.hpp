#pragma once
#include <immintrin.h>
#include <cstdint>
#include <algorithm>
#include "common/graph_types.hpp"

namespace traffic::router {

/**
 * @brief ALT Heuristics using AVX2 SIMD vectorization.
 * Computes max(|d(u,L) - d(t,L)|, |d(L,t) - d(L,u)|) over 32 landmarks.
 * Distances are stored in interleaved format: [to_L1, from_L1, to_L2, from_L2, ...]
 */
class ALTHeuristic {
public:
    /**
     * @brief Computes the ALT lower bound between node u and target t.
     * @param u_ptr Pointer to u's landmark distances (64 uint16_t, 32-byte aligned)
     * @param t_ptr Pointer to t's landmark distances (64 uint16_t, 32-byte aligned)
     */
    [[nodiscard]] inline PathWeight get_heuristic_avx2(const uint16_t* u_ptr, const uint16_t* t_ptr) const noexcept {
        __m256i max_vec = _mm256_setzero_si256();

        // Each loop iteration processes 16 uint16_t (8 landmarks, to and from)
        // Total 4 iterations = 64 uint16_t (32 landmarks)
        #pragma GCC unroll 4
        for (int i = 0; i < 4; ++i) {
            // Load 32 bytes (16 uint16_t) from u and t landmark data
            __m256i u_data = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + i * 16));
            __m256i t_data = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr + i * 16));

            // Saturated subtraction: epu16 handles non-negative result |d1 - d2|
            // sub1 = max(0, u - t)
            // sub2 = max(0, t - u)
            __m256i sub1 = _mm256_subs_epu16(u_data, t_data);
            __m256i sub2 = _mm256_subs_epu16(t_data, u_data);

            // combined = |u - t|
            __m256i combined = _mm256_max_epu16(sub1, sub2);
            max_vec = _mm256_max_epu16(max_vec, combined);
        }

        // Horizontal max over 256-bit register
        // 1. Fold 256 -> 128
        __m128i max_128 = _mm_max_epu16(_mm256_castsi256_si128(max_vec), _mm256_extracti128_si256(max_vec, 1));
        
        // 2. Cascaded horizontal max (128-bit)
        // Shift and max to reduce 8 elements (uint16) to 1
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 8)); // Max of [0..3] and [4..7]
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 4)); // Max of [0..1] and [2..3]
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 2)); // Max of 0 and 1

        return static_cast<PathWeight>(_mm_extract_epi16(max_128, 0));
    }
};

} // namespace traffic::router
