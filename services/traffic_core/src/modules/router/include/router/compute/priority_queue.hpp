#pragma once
#include <immintrin.h>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include <cstring>
#include "common/graph_types.hpp"
#include "router/compute/types.hpp"

namespace traffic::router {

/**
 * @brief EXTREME HFT STRICT 8-ARY SoA HEAP
 * Содержит Offset Trick для Aligned Loads и O(size) Memset очистку.
 */
class alignas(64) PriorityQueue {
    using NodeID = traffic::router::NodeID;
    using Weight = traffic::router::Weight;
    static constexpr Weight INF_WEIGHT = traffic::router::INF_WEIGHT;

    static constexpr uint32_t WEIGHT_OFFSET = 15;
    static constexpr uint32_t ELEMENT_OFFSET = 7;

public:
    PriorityQueue() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    
    ~PriorityQueue() { 
        if (raw_w_) std::free(raw_w_); 
        if (raw_e_) std::free(raw_e_); 
    }

    PriorityQueue(const PriorityQueue&) = delete;
    PriorityQueue& operator=(const PriorityQueue&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);

        cap_ = (cap + 31) & ~31;
        raw_w_ = static_cast<Weight*>(std::aligned_alloc(64, (cap_ + WEIGHT_OFFSET + 64) * sizeof(Weight)));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + ELEMENT_OFFSET + 64) * sizeof(traffic::PQElement)));
        
        weights_ = raw_w_ + WEIGHT_OFFSET;
        elements_ = raw_e_ + ELEMENT_OFFSET;
        
        // O(N) заполнение бесконечностями ТОЛЬКО один раз при старте
        if (raw_w_) {
            std::memset(raw_w_, 0xFF, (cap_ + WEIGHT_OFFSET + 64) * sizeof(Weight));
        }
        size_ = 0;
    }

    inline void clear() noexcept {
        // СВЕРХБЫСТРАЯ ОЧИСТКА: обнуляем только ту часть, что "испачкана" алгоритмом A*
        if (size_ > 0 && weights_) {
            std::memset(weights_, 0xFF, size_ * sizeof(Weight));
            size_ = 0;
        }
    }

    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 3;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; 
            elements_[idx] = elements_[p]; 
            idx = p;
        }
        weights_[idx] = el.weight; 
        elements_[idx] = el;
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        
        if (__builtin_expect(--size_ == 0, 0)) { 
            weights_[0] = INF_WEIGHT; 
            return top; 
        }

        Weight lw = weights_[size_]; 
        traffic::PQElement le = elements_[size_]; 
        weights_[size_] = INF_WEIGHT; // Инвариант: за пределами size_ всегда бесконечность

        uint32_t idx = 0;
        while (true) {
            uint32_t first = (idx << 3) + 1;
            
            // КРИТИЧЕСКИ ВАЖНО: сохраняет монолитность горячего цикла в L1i кэше
            // if (__builtin_expect(first >= size_, 0)) break;
            if (first >= size_) break;

            const __m256i* p_child = reinterpret_cast<const __m256i*>(&weights_[first]);
            __m256i v = _mm256_load_si256(p_child);
            
            __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
            __m256i m1 = _mm256_min_epu32(v, p1);
            __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
            __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
            Weight min_w = _mm256_extract_epi32(m3, 0);

            if (lw <= min_w) break;

            uint32_t mask = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w))));
            uint32_t min_idx = first + __builtin_ctz(mask);

            _mm_prefetch(reinterpret_cast<const char*>(&weights_[(min_idx << 3) + 1]), _MM_HINT_T0);

            weights_[idx] = weights_[min_idx]; 
            elements_[idx] = elements_[min_idx]; 
            idx = min_idx;
        }
        weights_[idx] = lw; 
        elements_[idx] = le;
        return top;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }

private:
    uint32_t size_, cap_;
    Weight* weights_;
    traffic::PQElement* elements_;
    Weight* raw_w_;
    traffic::PQElement* raw_e_;
};

} // namespace traffic::router