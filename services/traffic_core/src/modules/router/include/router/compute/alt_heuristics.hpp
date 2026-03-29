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
struct PreloadedTarget {
    __m256i t0, t1, t2, t3;
    
    inline void load(const uint16_t* t_ptr) noexcept {
        t0 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr));
        t1 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr + 16));
        t2 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr + 32));
        t3 = _mm256_load_si256(reinterpret_cast<const __m256i*>(t_ptr + 48));
    }
};

class ALTHeuristic {
public:
    /**
     * @brief Computes the ALT lower bound between node u and preloaded target.
     * @param u_ptr Pointer to u's landmark distances (64 uint16_t, 32-byte aligned)
     * @param target Preloaded target landmark distances in AVX2 registers.
     */
    [[nodiscard]] inline PathWeight get_heuristic_avx2(const uint16_t* u_ptr, const PreloadedTarget& target) const noexcept {
        __m256i u0 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr));
        __m256i s1_0 = _mm256_subs_epu16(u0, target.t0);
        __m256i s2_0 = _mm256_subs_epu16(target.t0, u0);
        __m256i max_vec = _mm256_max_epu16(s1_0, s2_0);

        __m256i u1 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + 16));
        __m256i s1_1 = _mm256_subs_epu16(u1, target.t1);
        __m256i s2_1 = _mm256_subs_epu16(target.t1, u1);
        max_vec = _mm256_max_epu16(max_vec, _mm256_max_epu16(s1_1, s2_1));

        __m256i u2 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + 32));
        __m256i s1_2 = _mm256_subs_epu16(u2, target.t2);
        __m256i s2_2 = _mm256_subs_epu16(target.t2, u2);
        max_vec = _mm256_max_epu16(max_vec, _mm256_max_epu16(s1_2, s2_2));

        __m256i u3 = _mm256_load_si256(reinterpret_cast<const __m256i*>(u_ptr + 48));
        __m256i s1_3 = _mm256_subs_epu16(u3, target.t3);
        __m256i s2_3 = _mm256_subs_epu16(target.t3, u3);
        max_vec = _mm256_max_epu16(max_vec, _mm256_max_epu16(s1_3, s2_3));

        __m128i max_128 = _mm_max_epu16(_mm256_castsi256_si128(max_vec), _mm256_extracti128_si256(max_vec, 1));
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 8));
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 4));
        max_128 = _mm_max_epu16(max_128, _mm_srli_si128(max_128, 2));

        return static_cast<PathWeight>(_mm_extract_epi16(max_128, 0));
    }
};

} // namespace traffic::router
