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
 * @brief STRICT 4-ARY HEAP (1-indexed, Sparse Aligned)
 * Spec: Root = 1. Children of i: 4i, 4i+1, 4i+2, 4i+3.
 * Advantages: 32-byte alignment for child blocks.
 */
class alignas(64) Strict4AryHeap {
public:
    Strict4AryHeap() : size_(0), capacity_(0), data_(nullptr) {}
    ~Strict4AryHeap() { if (data_) std::free(data_); }

    Strict4AryHeap(const Strict4AryHeap&) = delete;
    Strict4AryHeap& operator=(const Strict4AryHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= capacity_) return;
        if (data_) std::free(data_);
        capacity_ = (cap * 4 + 64);
        data_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (capacity_ + 16) * sizeof(traffic::PQElement)));
        clear();
    }

    inline void clear() noexcept {
        size_ = 0;
        if (data_) {
            for (size_t i = 0; i < capacity_ + 16; ++i) data_[i].weight = 0xFFFFFFFF;
        }
    }

    inline void push(traffic::PQElement el) noexcept {
        uint32_t p_idx = ++size_;
        while (p_idx > 1) {
            uint32_t parent = (p_idx + 2) >> 2;
            if (data_[parent].weight <= el.weight) break;
            data_[p_idx] = data_[parent];
            p_idx = parent;
        }
        data_[p_idx] = el;
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = data_[1];
        if (__builtin_expect(size_ == 1, 0)) { size_ = 0; data_[1].weight = 0xFFFFFFFF; return top; }
        traffic::PQElement last = data_[size_];
        data_[size_].weight = 0xFFFFFFFF;
        size_--;

        uint32_t idx = 1;
        while (true) {
            uint32_t first = (idx << 2) - 2; 
            if (first > size_) break;

            uint32_t m1 = (data_[first].weight < data_[first+1].weight) ? first : first+1;
            uint32_t m2 = (data_[first+2].weight < data_[first+3].weight) ? first+2 : first+3;
            uint32_t min_child = (data_[m1].weight < data_[m2].weight) ? m1 : m2;

            if (last.weight <= data_[min_child].weight) break;
            data_[idx] = data_[min_child];
            idx = min_child;
        }
        data_[idx] = last;
        return top;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }

private:
    uint32_t size_ = 0;
    size_t capacity_ = 0;
    traffic::PQElement* data_ = nullptr;
};

/**
 * @brief STRICT 8-ARY SoA HEAP (0-indexed, AVX2)
 */
class alignas(64) Strict8ArySoAHeap {
public:
    Strict8ArySoAHeap() : size_(0), capacity_(0), weights_(nullptr), elements_(nullptr) {}
    ~Strict8ArySoAHeap() { 
        if (weights_) std::free(weights_); 
        if (elements_) std::free(elements_); 
    }

    void reserve(size_t cap) {
        if (cap <= capacity_) return;
        if (weights_) std::free(weights_);
        if (elements_) std::free(elements_);

        capacity_ = (cap + 31) & ~31; 
        weights_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (capacity_ + 32) * sizeof(traffic::PathWeight)));
        elements_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (capacity_ + 32) * sizeof(traffic::PQElement)));
        clear();
    }

    inline void clear() noexcept {
        size_ = 0;
        if (weights_) {
            std::fill(weights_, weights_ + capacity_ + 32, 0xFFFFFFFF);
        }
    }

    inline void push(traffic::PQElement el) noexcept {
        size_t idx = size_++;
        while (idx > 0) {
            size_t parent = (idx - 1) >> 3; 
            if (weights_[parent] <= el.weight) break;
            weights_[idx] = weights_[parent];
            elements_[idx] = elements_[parent];
            idx = parent;
        }
        weights_[idx] = el.weight;
        elements_[idx] = el;
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        size_--;
        if (size_ > 0) {
            traffic::PathWeight last_w = weights_[size_];
            traffic::PQElement last_el = elements_[size_];
            weights_[size_] = 0xFFFFFFFF;

            size_t idx = 0;
            while (true) {
                size_t first = (idx << 3) + 1;
                if (first >= size_) break;

                __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first]));
                
                __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
                __m256i m1 = _mm256_min_epu32(v, p1);
                __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
                __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
                traffic::PathWeight min_w = _mm256_extract_epi32(m3, 0);

                if (last_w <= min_w) break;

                uint32_t mask = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w))));
                size_t min_idx = first + __builtin_ctz(mask);

                weights_[idx] = weights_[min_idx];
                elements_[idx] = elements_[min_idx];
                idx = min_idx;
            }
            weights_[idx] = last_w;
            elements_[idx] = last_el;
        }
        return top;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }

private:
    uint32_t size_ = 0;
    size_t capacity_ = 0;
    traffic::PathWeight* weights_ = nullptr;
    traffic::PQElement* elements_ = nullptr;
};

/**
 * @brief SAFE RADIX HEAP (Zero-Allocation version)
 */
class alignas(64) SafeRadixHeap {
private:
    struct FastBucket {
        traffic::PQElement* data = nullptr;
        uint32_t size = 0;
        uint32_t cap = 0;

        void push_back(traffic::PQElement el) {
            if (size == cap) {
                cap = cap ? cap * 2 : 64;
                data = static_cast<traffic::PQElement*>(std::realloc(data, cap * sizeof(traffic::PQElement)));
            }
            data[size++] = el;
        }
        inline traffic::PQElement pop_back() { return data[--size]; }
        inline void clear() { size = 0; }
        inline void destroy() { if (data) std::free(data); data = nullptr; cap = size = 0; }
        [[nodiscard]] inline bool empty() const { return size == 0; }
    };

public:
    SafeRadixHeap() : last_min_(0), size_(0), mask_(0) {
        for (int i = 0; i < 33; ++i) {
            buckets_[i].data = nullptr; buckets_[i].size = 0; buckets_[i].cap = 0;
        }
    }
    ~SafeRadixHeap() { for (int i = 0; i < 33; ++i) buckets_[i].destroy(); }

    inline void push(traffic::PQElement el) noexcept {
        uint32_t eff_val = (el.weight < last_min_) ? last_min_ : el.weight;
        uint32_t index = 32 - _lzcnt_u32(eff_val ^ last_min_);
        buckets_[index].push_back(el);
        size_++;
        mask_ |= (1ULL << index);
    }

    inline traffic::PQElement pop() noexcept {
        if (__builtin_expect(buckets_[0].empty(), 0)) fill_bucket0();
        traffic::PQElement top = buckets_[0].pop_back();
        if (buckets_[0].empty()) mask_ &= ~1ULL;
        size_--;
        return top;
    }

    inline void clear() noexcept {
        for (int i = 0; i < 33; ++i) buckets_[i].clear();
        last_min_ = 0; size_ = 0; mask_ = 0;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }
    inline void reserve(size_t) noexcept {}

private:
    void fill_bucket0() noexcept {
        uint64_t m = mask_ & ~1ULL;
        if (m == 0) return;
        uint32_t idx = __builtin_ctzll(m);
        FastBucket& bucket = buckets_[idx];
        traffic::PathWeight min_w = 0xFFFFFFFF;
        for (uint32_t i = 0; i < bucket.size; ++i) if (bucket.data[i].weight < min_w) min_w = bucket.data[i].weight;
        last_min_ = min_w;
        uint64_t local_mask = 0;
        for (uint32_t i = 0; i < bucket.size; ++i) {
            uint32_t index = 32 - _lzcnt_u32(bucket.data[i].weight ^ last_min_);
            buckets_[index].push_back(bucket.data[i]);
            local_mask |= (1ULL << index);
        }
        bucket.clear();
        mask_ &= ~(1ULL << idx);
        mask_ |= local_mask;
    }
    FastBucket buckets_[33];
    uint32_t last_min_;
    size_t size_;
    uint64_t mask_;
};

/**
 * @brief Legacy & Experimental structures for the Final Benchmark
 */
using Ultimate4AryHeap = Strict4AryHeap;
using Ultimate8ArySoAHeap = Strict8ArySoAHeap;

class alignas(64) SBBH {
    static constexpr uint32_t NUM_BUCKETS = 4096;
    static constexpr uint32_t BUCKET_MASK = 4095;
    struct Bucket {
        traffic::PQElement* data = nullptr; uint32_t size = 0; uint32_t cap = 0;
        void push(traffic::PQElement el) {
            if (size == cap) { cap = cap ? cap * 2 : 16; data = (traffic::PQElement*)realloc(data, cap * sizeof(traffic::PQElement)); }
            data[size++] = el;
        }
        traffic::PQElement pop_min() {
            uint32_t m = 0; for (uint32_t i = 1; i < size; ++i) if (data[i].weight < data[m].weight) m = i;
            traffic::PQElement r = data[m]; data[m] = data[--size]; return r;
        }
        void clear() { size = 0; }
        void destroy() { if (data) std::free(data); data = nullptr; size = cap = 0; }
        [[nodiscard]] bool empty() const { return size == 0; }
    };
public:
    SBBH() : size_(0), cur_(0), rm_(0) { std::memset(l1_, 0, sizeof(l1_)); }
    ~SBBH() { for (int i = 0; i < NUM_BUCKETS; ++i) b_[i].destroy(); }
    void reserve(size_t) {}
    void clear() { for (int i = 0; i < NUM_BUCKETS; ++i) b_[i].clear(); size_ = 0; cur_ = 0; rm_ = 0; std::memset(l1_, 0, sizeof(l1_)); }
    void push(traffic::PQElement el) {
        uint32_t i = el.weight & BUCKET_MASK; b_[i].push(el);
        l1_[i >> 6] |= (1ULL << (i & 63)); rm_ |= (1ULL << (i >> 6)); size_++;
    }
    traffic::PQElement pop() {
        uint32_t w = cur_ >> 6; uint64_t m = l1_[w] & (~0ULL << (cur_ & 63));
        if (!m) { uint64_t r = rm_ & (~0ULL << (w + 1)); if (!r) r = rm_; w = _tzcnt_u64(r); m = l1_[w]; }
        uint32_t i = (w << 6) | _tzcnt_u64(m); cur_ = i;
        traffic::PQElement r = b_[i].pop_min(); size_--;
        if (b_[i].empty()) { l1_[w] &= ~(1ULL << (i & 63)); if (!l1_[w]) rm_ &= ~(1ULL << w); }
        return r;
    }
    bool empty() const { return size_ == 0; }
    size_t size() const { return size_; }
private:
    size_t size_; uint32_t cur_; uint64_t rm_; uint64_t l1_[64]; Bucket b_[NUM_BUCKETS];
};

template<uint32_t S = 4>
class DeltaBucketQueue {
    static constexpr uint32_t NB = 8192;
    struct B {
        traffic::PQElement* d = nullptr; uint32_t s = 0; uint32_t c = 0;
        void p(traffic::PQElement el) { if (s == c) { c = c ? c * 2 : 16; d = (traffic::PQElement*)realloc(d, c * sizeof(traffic::PQElement)); } d[s++] = el; }
        void cl() { s = 0; } void de() { if (d) std::free(d); d = nullptr; s = c = 0; }
    };
public:
    DeltaBucketQueue() : sz_(0), mw_(0xFFFFFFFF) { }
    ~DeltaBucketQueue() { for (int i = 0; i < NB; ++i) b_[i].de(); }
    void reserve(size_t) {} void clear() { for (int i = 0; i < NB; ++i) b_[i].cl(); sz_ = 0; mw_ = 0xFFFFFFFF; }
    void push(traffic::PQElement el) { uint32_t i = (el.weight >> S) & (NB - 1); b_[i].p(el); sz_++; if (el.weight < mw_) mw_ = el.weight; }
    traffic::PQElement pop() {
        uint32_t i = (mw_ >> S) & (NB - 1); while (b_[i].s == 0) { mw_ += (1 << S); i = (mw_ >> S) & (NB - 1); }
        sz_--; return b_[i].d[--b_[i].s];
    }
    bool empty() const { return sz_ == 0; }
private:
    B b_[NB]; size_t sz_; uint32_t mw_;
};

/**
 * @brief Zero-Allocation Legacy structures for tests
 */
class Branchless4AryHeap {
public:
    Branchless4AryHeap() : size_(0), cap_(0), data_(nullptr) {}
    ~Branchless4AryHeap() { if (data_) std::free(data_); }
    void reserve(size_t cap) { if (cap > cap_) { cap_ = cap; data_ = (traffic::PQElement*)std::aligned_alloc(64, cap * sizeof(traffic::PQElement)); } clear(); }
    void clear() { size_ = 0; }
    void push(traffic::PQElement el) {
        uint32_t idx = size_++; uint32_t p = (idx - 1) / 4;
        while (idx > 0 && data_[p].weight > el.weight) { data_[idx] = data_[p]; idx = p; p = (idx - 1) / 4; }
        data_[idx] = el;
    }
    traffic::PQElement pop() {
        traffic::PQElement top = data_[0]; traffic::PQElement last = data_[--size_];
        uint32_t idx = 0;
        while (true) {
            uint32_t first = idx * 4 + 1; if (first >= size_) break;
            uint32_t m = first; for (uint32_t i = 1; i < 4; ++i) if (first + i < size_ && data_[first + i].weight < data_[m].weight) m = first + i;
            if (last.weight <= data_[m].weight) break; data_[idx] = data_[m]; idx = m;
        }
        data_[idx] = last; return top;
    }
    bool empty() const { return size_ == 0; }
private:
    uint32_t size_, cap_; traffic::PQElement* data_;
};

class SoA8AryAvx2Heap {
public:
    SoA8AryAvx2Heap() : size_(0), cap_(0), w_(nullptr), e_(nullptr) {}
    ~SoA8AryAvx2Heap() { if (w_) std::free(w_); if (e_) std::free(e_); }
    void reserve(size_t cap) {
        if (cap > cap_) {
            cap_ = (cap + 31) & ~31;
            w_ = (traffic::PathWeight*)std::aligned_alloc(64, (cap_ + 32) * sizeof(traffic::PathWeight));
            e_ = (traffic::PQElement*)std::aligned_alloc(64, (cap_ + 32) * sizeof(traffic::PQElement));
        }
        clear();
    }
    void clear() { size_ = 0; if (w_) std::fill(w_, w_ + cap_ + 32, 0xFFFFFFFF); }
    void push(traffic::PQElement el) {
        uint32_t idx = size_++; uint32_t p = (idx - 1) >> 3;
        while (idx > 0 && w_[p] > el.weight) { w_[idx] = w_[p]; e_[idx] = e_[p]; idx = p; p = (idx - 1) >> 3; }
        w_[idx] = el.weight; e_[idx] = el;
    }
    traffic::PQElement pop() {
        traffic::PQElement top = e_[0]; size_--;
        if (size_ > 0) {
            traffic::PathWeight lw = w_[size_]; traffic::PQElement le = e_[size_]; w_[size_] = 0xFFFFFFFF;
            uint32_t idx = 0;
            while (true) {
                uint32_t first = (idx << 3) + 1; if (first >= size_) break;
                __m256i v = _mm256_loadu_si256((__m256i*)&w_[first]);
                __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
                __m256i m1 = _mm256_min_epu32(v, p1);
                __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
                __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
                traffic::PathWeight min_w = _mm256_extract_epi32(m3, 0);
                if (lw <= min_w) break;
                uint32_t mask = _mm256_movemask_ps(_mm256_castsi256_ps(_mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w))));
                size_t min_idx = first + __builtin_ctz(mask);
                w_[idx] = w_[min_idx]; e_[idx] = e_[min_idx]; idx = min_idx;
            }
            w_[idx] = lw; e_[idx] = le;
        }
        return top;
    }
    bool empty() const { return size_ == 0; }
private:
    uint32_t size_, cap_; traffic::PathWeight* w_; traffic::PQElement* e_;
};

} // namespace traffic::router::compute
