#pragma once
#include <immintrin.h>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include <cassert>
#include <cstring>
#include "common/graph_types.hpp"
#include "router/compute/priority_queue.hpp"

namespace traffic::router::compute {

/**
 * @brief EXTREME HFT STRICT 8-ARY SoA HEAP
 */
class alignas(64) Strict8ArySoAEagerHeap {
    static constexpr uint32_t WEIGHT_OFFSET = 15;
    static constexpr uint32_t ELEMENT_OFFSET = 7;
public:
    Strict8ArySoAEagerHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict8ArySoAEagerHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict8ArySoAEagerHeap(const Strict8ArySoAEagerHeap&) = delete;
    Strict8ArySoAEagerHeap& operator=(const Strict8ArySoAEagerHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap_ = (cap + 31) & ~31;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + WEIGHT_OFFSET + 64) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + ELEMENT_OFFSET + 64) * 8));
        weights_ = raw_w_ + WEIGHT_OFFSET;
        elements_ = raw_e_ + ELEMENT_OFFSET;
        std::fill(raw_w_, raw_w_ + cap_ + WEIGHT_OFFSET + 64, 0xFFFFFFFF);
        size_ = 0;
    }
    inline void clear() noexcept {
        if (raw_w_ && size_ > 0) {
            std::fill(weights_, weights_ + size_ + 8, 0xFFFFFFFF);
        }
        size_ = 0;
    }
    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 3;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; elements_[idx] = elements_[p]; idx = p;
        }
        weights_[idx] = el.weight; elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { weights_[0] = 0xFFFFFFFF; return top; }
        traffic::PathWeight lw = weights_[size_]; traffic::PQElement le = elements_[size_]; weights_[size_] = 0xFFFFFFFF;
        uint32_t idx = 0;
        while (true) {
            uint32_t first = (idx << 3) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            const __m256i* p_child = reinterpret_cast<const __m256i*>(&weights_[first]);
            __m256i v = _mm256_loadu_si256(p_child);
            __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
            __m256i m1 = _mm256_min_epu32(v, p1);
            __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
            __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
            traffic::PathWeight min_w = _mm256_extract_epi32(m3, 0);
            if (lw <= min_w) break;
            uint32_t mask = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w))));
            uint32_t min_idx = first + __builtin_ctz(mask);
            _mm_prefetch(reinterpret_cast<const char*>(&weights_[(min_idx << 3) + 1]), _MM_HINT_T0);
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = lw; elements_[idx] = le;
        return top;
    }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }
private:
    uint32_t size_, cap_; traffic::PathWeight *weights_, *raw_w_; traffic::PQElement *elements_, *raw_e_;
};

/**
 * @brief STRICT 4-ARY SoA HEAP (SSE-Vectored SoA Heap)
 */
class alignas(64) Strict4AryHeap {
public:
    Strict4AryHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict4AryHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict4AryHeap(const Strict4AryHeap&) = delete;
    Strict4AryHeap& operator=(const Strict4AryHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap_ = (cap + 31) & ~31;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + 32) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + 32) * 8));
        weights_ = raw_w_;
        elements_ = raw_e_;
        std::fill(raw_w_, raw_w_ + cap_ + 32, 0xFFFFFFFF);
        size_ = 0;
    }
    inline void clear() noexcept {
        size_ = 0;
    }
    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 2;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; elements_[idx] = elements_[p]; idx = p;
        }
        weights_[idx] = el.weight; elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { weights_[0] = 0xFFFFFFFF; return top; }
        traffic::PathWeight lw = weights_[size_]; traffic::PQElement le = elements_[size_]; weights_[size_] = 0xFFFFFFFF;
        uint32_t idx = 0;
        
        while (true) {
            uint32_t first = (idx << 2) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            
            __m128i v = _mm_loadu_si128(reinterpret_cast<const __m128i*>(&weights_[first]));
            
            if (first + 4 > size_) {
                uint32_t valid_count = size_ - first;
                alignas(16) uint32_t mask_arr[4] = {0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF};
                for (uint32_t j = valid_count; j < 4; ++j) mask_arr[j] = 0;
                __m128i mask = _mm_load_si128(reinterpret_cast<const __m128i*>(mask_arr));
                __m128i inf = _mm_set1_epi32(0xFFFFFFFF);
                v = _mm_blendv_epi8(inf, v, mask);
            }
            
            __m128i m1 = _mm_min_epu32(v, _mm_shuffle_epi32(v, _MM_SHUFFLE(1, 0, 3, 2)));
            __m128i m2 = _mm_min_epu32(m1, _mm_shuffle_epi32(m1, _MM_SHUFFLE(2, 3, 0, 1)));
            traffic::PathWeight min_w = _mm_cvtsi128_si32(m2);
            
            if (lw <= min_w) break;
            
            uint32_t match_mask = _mm_movemask_ps(_mm_castsi128_ps(_mm_cmpeq_epi32(v, _mm_set1_epi32(min_w))));
            uint32_t min_idx = first + __builtin_ctz(match_mask);
            
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = lw; elements_[idx] = le;
        return top;
    }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
private:
    uint32_t size_, cap_; traffic::PathWeight *weights_, *raw_w_; traffic::PQElement *elements_, *raw_e_;
};

/**
 * @brief STRICT 2-ARY SoA HEAP (SSE-Optimized Binary Heap)
 */
class alignas(64) Strict2AryHeap {
public:
    Strict2AryHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict2AryHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict2AryHeap(const Strict2AryHeap&) = delete;
    Strict2AryHeap& operator=(const Strict2AryHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap = (cap + 31) & ~31;
        cap_ = cap;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + 32) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + 32) * 8));
        weights_ = raw_w_;
        elements_ = raw_e_;
        std::fill(raw_w_, raw_w_ + cap_ + 32, 0xFFFFFFFF);
        size_ = 0;
    }
    inline void clear() noexcept {
        size_ = 0;
    }
    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 1;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; elements_[idx] = elements_[p]; idx = p;
        }
        weights_[idx] = el.weight; elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { weights_[0] = 0xFFFFFFFF; return top; }
        traffic::PathWeight lw = weights_[size_]; traffic::PQElement le = elements_[size_]; weights_[size_] = 0xFFFFFFFF;
        uint32_t idx = 0;
        
        while (true) {
            uint32_t first = (idx << 1) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            
            if (first + 1 >= size_) {
                if (lw <= weights_[first]) break;
                weights_[idx] = weights_[first]; elements_[idx] = elements_[first]; idx = first;
                break;
            }
            
            uint32_t min_idx = first;
            if (weights_[first + 1] < weights_[first]) min_idx = first + 1;
            
            if (lw <= weights_[min_idx]) break;
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = lw; elements_[idx] = le;
        return top;
    }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
private:
    uint32_t size_, cap_; traffic::PathWeight *weights_, *raw_w_; traffic::PQElement *elements_, *raw_e_;
};

/**
 * @brief STRICT 8-ARY SoA LAZY HEAP (AVX2-Masked SoA Heap with O(1) clear)
 */
class alignas(64) Strict8ArySoALazyHeap {
    static constexpr uint32_t WEIGHT_OFFSET = 15;
    static constexpr uint32_t ELEMENT_OFFSET = 7;
public:
    Strict8ArySoALazyHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict8ArySoALazyHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict8ArySoALazyHeap(const Strict8ArySoALazyHeap&) = delete;
    Strict8ArySoALazyHeap& operator=(const Strict8ArySoALazyHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap_ = (cap + 31) & ~31;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + WEIGHT_OFFSET + 64) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + ELEMENT_OFFSET + 64) * 8));
        weights_ = raw_w_ + WEIGHT_OFFSET;
        elements_ = raw_e_ + ELEMENT_OFFSET;
        size_ = 0;
    }
    inline void clear() noexcept {
        size_ = 0;
    }
    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 3;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; elements_[idx] = elements_[p]; idx = p;
        }
        weights_[idx] = el.weight; elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { return top; }
        traffic::PathWeight lw = weights_[size_]; traffic::PQElement le = elements_[size_];
        uint32_t idx = 0;
        
        const __m256i v_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
        const __m256i inf = _mm256_set1_epi32(0xFFFFFFFF);
        const __m256i v_size = _mm256_set1_epi32(size_);
        
        while (true) {
            uint32_t first = (idx << 3) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            
            __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first]));
            
            // Векторное маскирование невалидных потомков на лету
            __m256i v_first = _mm256_set1_epi32(first);
            __m256i v_indices = _mm256_add_epi32(v_first, v_offsets);
            __m256i mask = _mm256_cmpgt_epi32(v_size, v_indices); // mask = 0xFFFFFFFF where index < size_
            v = _mm256_blendv_epi8(inf, v, mask);
            
            __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
            __m256i m1 = _mm256_min_epu32(v, p1);
            __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
            __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
            traffic::PathWeight min_w = _mm256_extract_epi32(m3, 0);
            if (lw <= min_w) break;
            uint32_t match_mask = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w))));
            uint32_t min_idx = first + __builtin_ctz(match_mask);
            _mm_prefetch(reinterpret_cast<const char*>(&weights_[(min_idx << 3) + 1]), _MM_HINT_T0);
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = lw; elements_[idx] = le;
        return top;
    }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }
private:
    uint32_t size_, cap_; traffic::PathWeight *weights_, *raw_w_; traffic::PQElement *elements_, *raw_e_;
};

/**
 * @brief STRICT 16-ARY SoA HEAP (AVX2-Vectored 16-Ary SoA Heap)
 */
class alignas(64) Strict16AryHeap {
public:
    Strict16AryHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict16AryHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict16AryHeap(const Strict16AryHeap&) = delete;
    Strict16AryHeap& operator=(const Strict16AryHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap = (cap + 31) & ~31;
        cap_ = cap;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + 32) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + 32) * 8));
        weights_ = raw_w_;
        elements_ = raw_e_;
        std::fill(raw_w_, raw_w_ + cap_ + 32, 0xFFFFFFFF);
        size_ = 0;
    }
    inline void clear() noexcept {
        size_ = 0;
    }
    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = size_++;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 4;
            if (weights_[p] <= el.weight) break;
            weights_[idx] = weights_[p]; elements_[idx] = elements_[p]; idx = p;
        }
        weights_[idx] = el.weight; elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { weights_[0] = 0xFFFFFFFF; return top; }
        traffic::PathWeight lw = weights_[size_]; traffic::PQElement le = elements_[size_]; weights_[size_] = 0xFFFFFFFF;
        uint32_t idx = 0;
        
        while (true) {
            uint32_t first = (idx << 4) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            
            __m256i v1 = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first]));
            __m256i v2 = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first + 8]));
            
            if (first + 16 > size_) {
                __m256i v_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
                __m256i inf = _mm256_set1_epi32(0xFFFFFFFF);
                __m256i v_size = _mm256_set1_epi32(size_);
                
                __m256i v_first1 = _mm256_set1_epi32(first);
                __m256i v_indices1 = _mm256_add_epi32(v_first1, v_offsets);
                __m256i mask1 = _mm256_cmpgt_epi32(v_size, v_indices1);
                v1 = _mm256_blendv_epi8(inf, v1, mask1);
                
                __m256i v_first2 = _mm256_set1_epi32(first + 8);
                __m256i v_indices2 = _mm256_add_epi32(v_first2, v_offsets);
                __m256i mask2 = _mm256_cmpgt_epi32(v_size, v_indices2);
                v2 = _mm256_blendv_epi8(inf, v2, mask2);
            }
            
            __m256i v = _mm256_min_epu32(v1, v2);
            __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
            __m256i m1 = _mm256_min_epu32(v, p1);
            __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
            __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
            traffic::PathWeight min_w = _mm256_extract_epi32(m3, 0);
            
            if (lw <= min_w) break;
            
            uint32_t mask1 = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v1, _mm256_set1_epi32(min_w))));
            uint32_t min_idx;
            if (mask1) {
                min_idx = first + __builtin_ctz(mask1);
            } else {
                uint32_t mask2 = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v2, _mm256_set1_epi32(min_w))));
                min_idx = first + 8 + __builtin_ctz(mask2);
            }
            
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = lw; elements_[idx] = le;
        return top;
    }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
private:
    uint32_t size_, cap_; traffic::PathWeight *weights_, *raw_w_; traffic::PQElement *elements_, *raw_e_;
};

/**
 * @brief RADIX HEAP (AVX2-Vectored Radix Heap)
 */
class alignas(64) SafeRadixHeap {
    struct B {
        traffic::PathWeight* w;
        traffic::PQElement* e;
        uint32_t s, c;
        
        inline void p(traffic::PathWeight weight, traffic::PQElement el) noexcept {
            if (s == c) {
                c = c ? c * 2 : 64;
                w = static_cast<traffic::PathWeight*>(std::realloc(w, c * sizeof(traffic::PathWeight)));
                e = static_cast<traffic::PQElement*>(std::realloc(e, c * sizeof(traffic::PQElement)));
            }
            w[s] = weight;
            e[s] = el;
            s++;
        }
        inline void de() noexcept {
            if (w) std::free(w);
            if (e) std::free(e);
            w = nullptr;
            e = nullptr;
            s = c = 0;
        }
    };
public:
    SafeRadixHeap() : lm_(0), sz_(0), ms_(0) { std::memset(b_, 0, sizeof(b_)); }
    ~SafeRadixHeap() { for (int i = 0; i < 33; ++i) b_[i].de(); }
    
    inline void push(traffic::PQElement el) noexcept {
        uint32_t v = (el.weight < lm_) ? lm_ : el.weight;
        uint32_t i = 32 - _lzcnt_u32(v ^ lm_);
        b_[i].p(el.weight, el);
        sz_++;
        ms_ |= (1ULL << i);
    }
    
    inline traffic::PQElement pop() noexcept {
        if (b_[0].s == 0) {
            uint64_t m = ms_ & ~1ULL;
            if (!m) return {0, 0};
            uint32_t idx = __builtin_ctzll(m);
            B& b = b_[idx];
            
            traffic::PathWeight mw = 0xFFFFFFFF;
            uint32_t i = 0;
            if (b.s >= 8) {
                __m256i v_min = _mm256_set1_epi32(0xFFFFFFFF);
                for (; i + 7 < b.s; i += 8) {
                    __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&b.w[i]));
                    v_min = _mm256_min_epu32(v_min, v);
                }
                __m256i p1 = _mm256_permute2x128_si256(v_min, v_min, 1);
                __m256i m1 = _mm256_min_epu32(v_min, p1);
                __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
                __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
                mw = _mm256_extract_epi32(m3, 0);
            }
            for (; i < b.s; ++i) {
                if (b.w[i] < mw) mw = b.w[i];
            }
            
            lm_ = mw;
            uint64_t nm = 0;
            for (uint32_t j = 0; j < b.s; ++j) {
                uint32_t ni = 32 - _lzcnt_u32(b.w[j] ^ lm_);
                b_[ni].p(b.w[j], b.e[j]);
                nm |= (1ULL << ni);
            }
            b.s = 0;
            ms_ &= ~(1ULL << idx);
            ms_ |= nm;
        }
        traffic::PQElement r = b_[0].e[--b_[0].s];
        if (b_[0].s == 0) ms_ &= ~1ULL;
        sz_--;
        return r;
    }
    [[nodiscard]] inline bool empty() const noexcept { return sz_ == 0; }
    inline void clear() noexcept {
        for (int i = 0; i < 33; ++i) b_[i].s = 0;
        lm_ = sz_ = 0;
        ms_ = 0;
    }
    inline void reserve(size_t) noexcept {}
private:
    B b_[33];
    uint32_t lm_;
    size_t sz_;
    uint64_t ms_;
};

/**
 * @brief АКАДЕМИЧЕСКАЯ СПРАВКА: Bucket Queue (Очередь Диала / Dial's Algorithm, 1969)
 * 
 * В академической теории Диала Bucket Queue является СТРОГОЙ (Strict) структурой данных,
 * где размер каждого ведра равен 1 (S = 0, Delta = 1). Это гарантирует, что внутри каждой 
 * корзины находятся элементы с абсолютно одинаковым весом, делая извлечение минимума строго 
 * монотонным без внутренней сортировки. 
 * 
 * В данной реализации при S > 0 (шаг Delta = 16) структура переходит в класс Approximate 
 * Bucket Queue. За счет этого достигается высокая скорость обработки, но из-за отсутствия 
 * внутренней сортировки элементов в корзине (извлечение LIFO/FIFO в pop()) она допускает 
 * теоретическую субоптимальность путей в пределах окна Delta (16), что требует допуска 
 * погрешности в тестах.
 */
template<uint32_t S = 4>
class DeltaBucketQueue {
    struct B { 
        traffic::PQElement* d; uint32_t s, c; 
        void p(traffic::PQElement el) { if (s == c) { c = c ? c * 2 : 16; d = (traffic::PQElement*)realloc(d, c * 8); } d[s++] = el; } 
        void de() { if (d) free(d); }
    };
public:
    DeltaBucketQueue() : sz_(0), mw_(0xFFFFFFFF), max_w_(0) { std::memset(b_, 0, sizeof(b_)); }
    ~DeltaBucketQueue() { for (int i = 0; i < 8192; ++i) b_[i].de(); }
    void push(traffic::PQElement el) { 
        uint32_t i = (el.weight >> S) & 8191; 
        b_[i].p(el); 
        sz_++; 
        if (el.weight < mw_) mw_ = el.weight; 
        if (el.weight > max_w_) max_w_ = el.weight;
    }
    traffic::PQElement pop() {
        uint32_t i = (mw_ >> S) & 8191; while (b_[i].s == 0) { mw_ += (1 << S); i = (mw_ >> S) & 8191; }
        sz_--; return b_[i].d[--b_[i].s];
    }
    bool empty() const { return sz_ == 0; }
    void reserve(size_t) {} 
    void clear() { 
        if (sz_ > 0 && mw_ != 0xFFFFFFFF && max_w_ != 0) {
            uint32_t start_idx = (mw_ >> S) & 8191;
            uint32_t end_idx = (max_w_ >> S) & 8191;
            if (end_idx >= start_idx) {
                for (uint32_t i = start_idx; i <= end_idx; ++i) b_[i].s = 0;
            } else {
                for (uint32_t i = start_idx; i < 8192; ++i) b_[i].s = 0;
                for (uint32_t i = 0; i <= end_idx; ++i) b_[i].s = 0;
            }
        }
        sz_ = 0; mw_ = 0xFFFFFFFF; max_w_ = 0;
    }
private:
    B b_[8192]; size_t sz_; uint32_t mw_; uint32_t max_w_;
};



/**
 * @brief АКАДЕМИЧЕСКАЯ СПРАВКА: Delta-Stepping Queue (Meyer & Sanders, 1998)
 * 
 * В академической литературе Delta-stepping разрабатывался как высокопроизводительный параллельный 
 * алгоритм обсчета графов, разбивающий диапазон весов на корзины фиксированного размера Delta (S > 0). 
 * Вершины внутри текущего «дельта-ведра» обрабатываются параллельно. Возникающие ошибки монотонности 
 * из-за несортированности внутри ведра разрешаются повторными релаксациями в последующих фазах.
 * 
 * В данной последовательной (однопоточной) реализации DeltaQueue превращена в Approximate Delta Queue,
 * оптимизированную с помощью кольцевого буфера и битовых масок. Она заменяет параллельный обход на 
 * быстрое последовательное сканирование активных ведер, сохраняя высокую скорость на CPU ценой 
 * микро-субоптимальности при S > 0, компенсируемой в тестах.
 */
class alignas(64) DeltaQueue {
    static constexpr uint32_t S = 4; // Delta = 16
    static constexpr uint32_t NUM_BUCKETS = 8192;
    static constexpr uint32_t MASK = NUM_BUCKETS - 1;

    struct B { 
        traffic::PQElement* d; uint32_t s, c; 
        inline void p(traffic::PQElement el) noexcept { 
            if (s == c) { 
                c = c ? c * 2 : 16; 
                d = (traffic::PQElement*)std::realloc(d, c * sizeof(traffic::PQElement)); 
            } 
            d[s++] = el; 
        } 
        inline void de() noexcept { if (d) std::free(d); d = nullptr; s = c = 0; }
    };
public:
    DeltaQueue() : sz_(0), mw_(0xFFFFFFFF), max_w_(0) { std::memset(b_, 0, sizeof(b_)); }
    ~DeltaQueue() { for (uint32_t i = 0; i < NUM_BUCKETS; ++i) b_[i].de(); }
    
    inline void push(traffic::PQElement el) noexcept { 
        uint32_t i = (el.weight >> S) & MASK; 
        b_[i].p(el); 
        sz_++; 
        if (el.weight < mw_) mw_ = el.weight; 
        if (el.weight > max_w_) max_w_ = el.weight;
    }
    
    inline traffic::PQElement pop() noexcept {
        uint32_t i = (mw_ >> S) & MASK; 
        while (b_[i].s == 0) { 
            mw_ += (1 << S); 
            i = (mw_ >> S) & MASK; 
        }
        sz_--; 
        return b_[i].d[--b_[i].s];
    }
    
    [[nodiscard]] inline bool empty() const noexcept { return sz_ == 0; }
    inline void reserve(size_t) noexcept {} 
    
    inline void clear() noexcept { 
        if (sz_ > 0 && mw_ != 0xFFFFFFFF && max_w_ != 0) {
            uint32_t start_idx = (mw_ >> S) & MASK;
            uint32_t end_idx = (max_w_ >> S) & MASK;
            if (end_idx >= start_idx) {
                for (uint32_t i = start_idx; i <= end_idx; ++i) b_[i].s = 0;
            } else {
                for (uint32_t i = start_idx; i < NUM_BUCKETS; ++i) b_[i].s = 0;
                for (uint32_t i = 0; i <= end_idx; ++i) b_[i].s = 0;
            }
        }
        sz_ = 0; 
        mw_ = 0xFFFFFFFF; 
        max_w_ = 0;
    }
private:
    B b_[NUM_BUCKETS]; 
    size_t sz_; 
    uint32_t mw_;
    uint32_t max_w_;
};

using Strict8ArySoAHeap = Strict8ArySoAEagerHeap;

using Ultimate4AryHeap = Strict4AryHeap;
using Ultimate8AryHeap = Strict8ArySoALazyHeap;
using Ultimate8ArySoAHeap = Strict8ArySoAEagerHeap;
using Branchless4AryHeap = Strict4AryHeap;
using SoA8AryAvx2Heap = Strict8ArySoAEagerHeap;

} // namespace traffic::router::compute
