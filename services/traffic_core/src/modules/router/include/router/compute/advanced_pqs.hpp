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
class alignas(64) Strict8ArySoAHeap {
    static constexpr uint32_t WEIGHT_OFFSET = 15;
    static constexpr uint32_t ELEMENT_OFFSET = 7;
public:
    Strict8ArySoAHeap() : size_(0), cap_(0), weights_(nullptr), elements_(nullptr), raw_w_(nullptr), raw_e_(nullptr) {}
    ~Strict8ArySoAHeap() { if (raw_w_) std::free(raw_w_); if (raw_e_) std::free(raw_e_); }
    Strict8ArySoAHeap(const Strict8ArySoAHeap&) = delete;
    Strict8ArySoAHeap& operator=(const Strict8ArySoAHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= cap_) return;
        if (raw_w_) std::free(raw_w_);
        if (raw_e_) std::free(raw_e_);
        cap_ = (cap + 31) & ~31;
        raw_w_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (cap_ + WEIGHT_OFFSET + 64) * 4));
        raw_e_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (cap_ + ELEMENT_OFFSET + 64) * 8));
        weights_ = raw_w_ + WEIGHT_OFFSET;
        elements_ = raw_e_ + ELEMENT_OFFSET;
        clear();
    }
    inline void clear() noexcept {
        size_ = 0;
        if (raw_w_) std::fill(raw_w_, raw_w_ + cap_ + WEIGHT_OFFSET + 64, 0xFFFFFFFF);
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
            __m256i v = _mm256_load_si256(p_child);
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
 * @brief STRICT 4-ARY HEAP
 */
class alignas(64) Strict4AryHeap {
public:
    Strict4AryHeap() : s_(0), c_(0), d_(nullptr) {}
    ~Strict4AryHeap() { if (d_) std::free(d_); }
    void reserve(size_t c) { if (c > c_) { c_ = c; d_ = (traffic::PQElement*)std::aligned_alloc(64, c * sizeof(traffic::PQElement)); } clear(); }
    void clear() { s_ = 0; }
    void push(traffic::PQElement el) {
        uint32_t i = s_++;
        while (i > 0) { uint32_t p = (i - 1) / 4; if (d_[p].weight <= el.weight) break; d_[i] = d_[p]; i = p; }
        d_[i] = el;
    }
    traffic::PQElement pop() {
        traffic::PQElement t = d_[0], l = d_[--s_]; uint32_t idx = 0;
        while (1) {
            uint32_t f = idx * 4 + 1; if (f >= s_) break;
            uint32_t m = f; for (int j = 1; j < 4; ++j) if (f + j < s_ && d_[f + j].weight < d_[m].weight) m = f + j;
            if (l.weight <= d_[m].weight) break; d_[idx] = d_[m]; idx = m;
        }
        d_[idx] = l; return t;
    }
    bool empty() const { return s_ == 0; }
private:
    uint32_t s_, c_; traffic::PQElement* d_;
};

/**
 * @brief STRICT 2-ARY HEAP (Binary Heap)
 */
class alignas(64) Strict2AryHeap {
public:
    Strict2AryHeap() : s_(0), c_(0), d_(nullptr) {}
    ~Strict2AryHeap() { if (d_) std::free(d_); }
    void reserve(size_t c) { if (c > c_) { c_ = c; d_ = (traffic::PQElement*)std::aligned_alloc(64, c * sizeof(traffic::PQElement)); } clear(); }
    void clear() { s_ = 0; }
    void push(traffic::PQElement el) {
        uint32_t i = s_++;
        while (i > 0) { uint32_t p = (i - 1) / 2; if (d_[p].weight <= el.weight) break; d_[i] = d_[p]; i = p; }
        d_[i] = el;
    }
    traffic::PQElement pop() {
        traffic::PQElement t = d_[0], l = d_[--s_]; uint32_t idx = 0;
        while (1) {
            uint32_t f = idx * 2 + 1; if (f >= s_) break;
            uint32_t m = f; if (f + 1 < s_ && d_[f + 1].weight < d_[m].weight) m = f + 1;
            if (l.weight <= d_[m].weight) break; d_[idx] = d_[m]; idx = m;
        }
        d_[idx] = l; return t;
    }
    bool empty() const { return s_ == 0; }
private:
    uint32_t s_, c_; traffic::PQElement* d_;
};

/**
 * @brief STRICT 16-ARY HEAP
 */
class alignas(64) Strict16AryHeap {
public:
    Strict16AryHeap() : s_(0), c_(0), d_(nullptr) {}
    ~Strict16AryHeap() { if (d_) std::free(d_); }
    void reserve(size_t c) { if (c > c_) { c_ = c; d_ = (traffic::PQElement*)std::aligned_alloc(64, c * sizeof(traffic::PQElement)); } clear(); }
    void clear() { s_ = 0; }
    void push(traffic::PQElement el) {
        uint32_t i = s_++;
        while (i > 0) { uint32_t p = (i - 1) / 16; if (d_[p].weight <= el.weight) break; d_[i] = d_[p]; i = p; }
        d_[i] = el;
    }
    traffic::PQElement pop() {
        traffic::PQElement t = d_[0], l = d_[--s_]; uint32_t idx = 0;
        while (1) {
            uint32_t f = idx * 16 + 1; if (f >= s_) break;
            uint32_t m = f; for (int j = 1; j < 16; ++j) if (f + j < s_ && d_[f + j].weight < d_[m].weight) m = f + j;
            if (l.weight <= d_[m].weight) break; d_[idx] = d_[m]; idx = m;
        }
        d_[idx] = l; return t;
    }
    bool empty() const { return s_ == 0; }
private:
    uint32_t s_, c_; traffic::PQElement* d_;
};

/**
 * @brief RADIX HEAP (Legacy)
 */
class alignas(64) SafeRadixHeap {
    struct B {
        traffic::PQElement* d; uint32_t s, c;
        void p(traffic::PQElement el) { if (s == c) { c = c ? c * 2 : 64; d = (traffic::PQElement*)realloc(d, c * sizeof(traffic::PQElement)); } d[s++] = el; }
        void de() { if (d) free(d); }
    };
public:
    SafeRadixHeap() : lm_(0), sz_(0), ms_(0) { std::memset(b_, 0, sizeof(b_)); }
    ~SafeRadixHeap() { for (int i = 0; i < 33; ++i) b_[i].de(); }
    void push(traffic::PQElement el) {
        uint32_t v = (el.weight < lm_) ? lm_ : el.weight;
        uint32_t i = 32 - _lzcnt_u32(v ^ lm_); b_[i].p(el); sz_++; ms_ |= (1ULL << i);
    }
    traffic::PQElement pop() {
        if (b_[0].s == 0) {
            uint64_t m = ms_ & ~1ULL; if (!m) return {0, 0};
            uint32_t idx = __builtin_ctzll(m); B& b = b_[idx];
            traffic::PathWeight mw = 0xFFFFFFFF; for (uint32_t i = 0; i < b.s; ++i) if (b.d[i].weight < mw) mw = b.d[i].weight;
            lm_ = mw; uint64_t nm = 0;
            for (uint32_t i = 0; i < b.s; ++i) { uint32_t ni = 32 - _lzcnt_u32(b.d[i].weight ^ lm_); b_[ni].p(b.d[i]); nm |= (1ULL << ni); }
            b.s = 0; ms_ &= ~(1ULL << idx); ms_ |= nm;
        }
        traffic::PQElement r = b_[0].d[--b_[0].s]; if (b_[0].s == 0) ms_ &= ~1ULL; sz_--; return r;
    }
    bool empty() const { return sz_ == 0; }
    void clear() { for (int i = 0; i < 33; ++i) b_[i].s = 0; lm_ = sz_ = 0; ms_ = 0; }
    void reserve(size_t) {}
private:
    B b_[33]; uint32_t lm_; size_t sz_; uint64_t ms_;
};

/**
 * @brief DELTA BUCKET QUEUE
 */
template<uint32_t S = 4>
class DeltaBucketQueue {
    struct B { 
        traffic::PQElement* d; uint32_t s, c; 
        void p(traffic::PQElement el) { if (s == c) { c = c ? c * 2 : 16; d = (traffic::PQElement*)realloc(d, c * 8); } d[s++] = el; } 
        void de() { if (d) free(d); }
    };
public:
    DeltaBucketQueue() : sz_(0), mw_(0xFFFFFFFF) { std::memset(b_, 0, sizeof(b_)); }
    ~DeltaBucketQueue() { for (int i = 0; i < 8192; ++i) b_[i].de(); }
    void push(traffic::PQElement el) { uint32_t i = (el.weight >> S) & 8191; b_[i].p(el); sz_++; if (el.weight < mw_) mw_ = el.weight; }
    traffic::PQElement pop() {
        uint32_t i = (mw_ >> S) & 8191; while (b_[i].s == 0) { mw_ += (1 << S); i = (mw_ >> S) & 8191; }
        sz_--; return b_[i].d[--b_[i].s];
    }
    bool empty() const { return sz_ == 0; }
    void reserve(size_t) {} 
    void clear() { sz_ = 0; mw_ = 0xFFFFFFFF; for (int i = 0; i < 8192; ++i) b_[i].s = 0; }
private:
    B b_[8192]; size_t sz_; uint32_t mw_;
};

/**
 * @brief SBBH (SIMD Bucket-Backed Heap)
 */
class alignas(64) SBBH {
    struct B {
        traffic::PQElement* d; uint32_t s, c;
        void p(traffic::PQElement el) { if (s == c) { c = c ? c * 2 : 16; d = (traffic::PQElement*)realloc(d, c * 8); } d[s++] = el; }
        traffic::PQElement pm() {
            uint32_t m = 0; for (uint32_t i = 1; i < s; ++i) if (d[i].weight < d[m].weight) m = i;
            traffic::PQElement r = d[m]; d[m] = d[--s]; return r;
        }
        void de() { if (d) free(d); }
    };
public:
    SBBH() : sz_(0), cur_(0), rm_(0) { std::memset(l1_, 0, sizeof(l1_)); std::memset(b_, 0, sizeof(b_)); }
    ~SBBH() { for (int i = 0; i < 4096; ++i) b_[i].de(); }
    void push(traffic::PQElement el) {
        uint32_t i = el.weight & 4095; b_[i].p(el);
        l1_[i >> 6] |= (1ULL << (i & 63)); rm_ |= (1ULL << (i >> 6)); sz_++;
    }
    traffic::PQElement pop() {
        uint32_t w = cur_ >> 6; uint64_t m = l1_[w] & (~0ULL << (cur_ & 63));
        if (!m) { uint64_t r = rm_ & (~0ULL << (w + 1)); if (!r) r = rm_; w = _tzcnt_u64(r); m = l1_[w]; }
        uint32_t i = (w << 6) | _tzcnt_u64(m); cur_ = i;
        traffic::PQElement r = b_[i].pm(); sz_--;
        if (b_[i].s == 0) { l1_[w] &= ~(1ULL << (i & 63)); if (!l1_[w]) rm_ &= ~(1ULL << w); }
        return r;
    }
    bool empty() const { return sz_ == 0; }
    void reserve(size_t) {}
    void clear() { sz_ = 0; cur_ = 0; rm_ = 0; std::memset(l1_, 0, sizeof(l1_)); for (int i = 0; i < 4096; ++i) b_[i].s = 0; }
private:
    size_t sz_; uint32_t cur_; uint64_t rm_, l1_[64]; B b_[4096];
};

using Ultimate4AryHeap = Strict4AryHeap;
using Ultimate8ArySoAHeap = Strict8ArySoAHeap;
using Branchless4AryHeap = Strict4AryHeap;
using SoA8AryAvx2Heap = Strict8ArySoAHeap;

} // namespace traffic::router::compute
