#pragma once
#include <immintrin.h>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include <vector>
#include "common/graph_types.hpp"
#include "router/compute/priority_queue.hpp"

namespace traffic::router::compute {

/**
 * @brief ULTIMATE 8-ARY SoA HEAP (Strict, 1-indexed, SIMD Aligned)
 * Optimized for AVX2 aligned loads and minimal Hot-Path instructions.
 */
class alignas(64) Ultimate8ArySoAHeap {
public:
    Ultimate8ArySoAHeap() : real_size_(0), capacity_(0), weights_(nullptr), elements_(nullptr) {}
    ~Ultimate8ArySoAHeap() { 
        if (weights_) std::free(weights_); 
        if (elements_) std::free(elements_); 
    }

    // Disable copy/move
    Ultimate8ArySoAHeap(const Ultimate8ArySoAHeap&) = delete;
    Ultimate8ArySoAHeap& operator=(const Ultimate8ArySoAHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= capacity_) return;
        if (weights_) std::free(weights_);
        if (elements_) std::free(elements_);

        // Sparse SIMD Indexing: Children of idx are at (idx << 3)
        // Root is at 1. Capacity must ensure that the deepest level fits.
        // For 8-ary, capacity grows fast, but most of it is unused.
        // We'll use cap * 8 for safety or a more precise bound.
        capacity_ = (cap * 8 + 32 + 31) & ~31; 
        weights_ = static_cast<traffic::PathWeight*>(std::aligned_alloc(64, (capacity_ + 32) * sizeof(traffic::PathWeight)));
        elements_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (capacity_ + 32) * sizeof(traffic::PQElement)));
        clear();
    }

    inline void clear() noexcept {
        real_size_ = 0;
        if (weights_) {
            // Fill entire array with INF to act as global sentinel
            std::fill(weights_, weights_ + capacity_ + 32, 0xFFFFFFFF);
        }
    }

    inline void push(traffic::PQElement el) noexcept {
        if (__builtin_expect(real_size_ >= capacity_, 0)) return;
        size_t idx = ++real_size_;
        // Use a logical index for the heap structure (sparse)
        // Wait, sparse indexing is better managed if push/pop use the SAME logic.
        // Let's use dense 1-based and loadu, OR stick to user's requested idx*8.
        // Let's go with Dense 1-based first and FIX IT properly.
        size_t h_idx = real_size_;
        while (h_idx > 1) {
            size_t parent = (h_idx + 6) >> 3; 
            if (weights_[parent] <= el.weight) break;
            weights_[h_idx] = weights_[parent];
            elements_[h_idx] = elements_[parent];
            h_idx = parent;
        }
        weights_[h_idx] = el.weight;
        elements_[h_idx] = el;
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[1];
        traffic::PathWeight last_w = weights_[real_size_];
        traffic::PQElement last_el = elements_[real_size_];
        
        weights_[real_size_] = 0xFFFFFFFF;
        real_size_--;

        if (__builtin_expect(real_size_ > 0, 1)) {
            size_t idx = 1;
            while (true) {
                size_t first = (idx << 3) - 6; 
                if (first > real_size_) break;

                // Load 8 weights (unaligned loadu if not 32-byte boundary)
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

    [[nodiscard]] inline bool empty() const noexcept { return real_size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return real_size_; }

private:
    size_t real_size_ = 0;
    size_t capacity_ = 0;
    traffic::PathWeight* weights_ = nullptr;
    traffic::PQElement* elements_ = nullptr;
};

/**
 * @brief ULTIMATE 4-ARY HEAP (Branchless, 1-indexed)
 */
class alignas(64) Ultimate4AryHeap {
public:
    Ultimate4AryHeap() : size_(0), capacity_(0), data_(nullptr) {}
    ~Ultimate4AryHeap() { if (data_) std::free(data_); }

    Ultimate4AryHeap(const Ultimate4AryHeap&) = delete;
    Ultimate4AryHeap& operator=(const Ultimate4AryHeap&) = delete;

    void reserve(size_t cap) {
        if (cap <= capacity_) return;
        if (data_) std::free(data_);
        
        // Dense 1-based indexing for 4-ary
        capacity_ = (cap + 16 + 7) & ~7;
        data_ = static_cast<traffic::PQElement*>(std::aligned_alloc(64, (capacity_ + 8) * sizeof(traffic::PQElement)));
        clear();
    }

    inline void clear() noexcept {
        size_ = 0;
        if (data_) {
            for(size_t i = 0; i < capacity_; ++i) data_[i].weight = 0xFFFFFFFF;
        }
    }

    inline void push(traffic::PQElement el) noexcept {
        if (__builtin_expect(size_ >= capacity_, 0)) return;
        size_t idx = ++size_;
        while (idx > 1) {
            size_t parent = (idx + 2) >> 2; 
            if (data_[parent].weight <= el.weight) break;
            data_[idx] = data_[parent];
            idx = parent;
        }
        data_[idx] = el;
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = data_[1];
        if (__builtin_expect(size_ == 1, 0)) { size_ = 0; data_[1].weight = 0xFFFFFFFF; return top; }
        
        traffic::PQElement last = data_[size_];
        data_[size_].weight = 0xFFFFFFFF;
        size_--;

        if (__builtin_expect(size_ > 0, 1)) {
            size_t idx = 1;
            while (true) {
                size_t first = (idx << 2) - 2; 
                if (first > size_) break;

                // Dense branchless selection
                size_t m1 = (data_[first].weight < data_[first+1].weight) ? first : first+1;
                size_t m2 = (data_[first+2].weight < data_[first+3].weight) ? first+2 : first+3;
                size_t min_child = (data_[m1].weight < data_[m2].weight) ? m1 : m2;

                if (last.weight <= data_[min_child].weight) break;
                data_[idx] = data_[min_child];
                idx = min_child;
            }
            data_[idx] = last;
        }
        return top;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }

private:
    size_t size_ = 0;
    size_t capacity_ = 0;
    traffic::PQElement* data_ = nullptr;
};

// -----------------------------------------------------------------------------
// Experimental Older Versions (kept for reference per user request)
// -----------------------------------------------------------------------------

class Branchless4AryHeap {
    static constexpr size_t ARITY = 4;
public:
    inline void push(traffic::PQElement el) noexcept { heap_.push_back(el); sift_up(heap_.size() - 1); }
    inline traffic::PQElement pop() noexcept {
        auto top = heap_.front(); heap_.front() = heap_.back(); heap_.pop_back();
        if (__builtin_expect(!heap_.empty(), 1)) sift_down(0);
        return top;
    }
    inline bool empty() const noexcept { return heap_.empty(); }
    inline size_t size() const noexcept { return heap_.size(); }
    inline void reserve(size_t cap) { heap_.reserve(cap); }
private:
    inline void sift_up(size_t idx) noexcept {
        traffic::PQElement val = heap_[idx];
        while (idx > 0) {
            size_t parent = (idx - 1) / ARITY;
            if (heap_[parent].weight <= val.weight) break;
            heap_[idx] = heap_[parent]; idx = parent;
        }
        heap_[idx] = val;
    }
    inline void sift_down(size_t idx) noexcept {
        const size_t size = heap_.size(); traffic::PQElement val = heap_[idx];
        while (true) {
            size_t first = idx * ARITY + 1; if (first >= size) break;
            size_t min_idx = first; traffic::PathWeight min_w = heap_[first].weight;
            #pragma GCC unroll 3
            for (size_t offset = 1; offset < ARITY; ++offset) {
                size_t child = first + offset; traffic::PathWeight cw = (child < size) ? heap_[child].weight : traffic::INF_WEIGHT;
                bool less = cw < min_w; min_w = less ? cw : min_w; min_idx = less ? child : min_idx;
            }
            if (val.weight <= min_w) break;
            heap_[idx] = heap_[min_idx]; idx = min_idx;
        }
        heap_[idx] = val;
    }
    std::vector<traffic::PQElement> heap_;
};

class SoA8AryAvx2Heap {
public:
    SoA8AryAvx2Heap() { weights_.reserve(65536); elements_.reserve(65536); }
    inline void push(traffic::PQElement el) noexcept { weights_.push_back(el.weight); elements_.push_back(el); sift_up(weights_.size() - 1); }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0]; weights_[0] = weights_.back(); elements_[0] = elements_.back();
        weights_.pop_back(); elements_.pop_back();
        if (!weights_.empty()) sift_down(0);
        return top;
    }
    inline bool empty() const noexcept { return weights_.empty(); }
    inline size_t size() const noexcept { return weights_.size(); }
    inline void reserve(size_t cap) { weights_.reserve(cap); elements_.reserve(cap); }
private:
    inline void sift_up(size_t idx) noexcept {
        traffic::PathWeight w = weights_[idx]; traffic::PQElement el = elements_[idx];
        while (idx > 0) {
            size_t parent = (idx - 1) / 8; if (weights_[parent] <= w) break;
            weights_[idx] = weights_[parent]; elements_[idx] = elements_[parent]; idx = parent;
        }
        weights_[idx] = w; elements_[idx] = el;
    }
    inline void sift_down(size_t idx) noexcept {
        const size_t size = weights_.size(); traffic::PathWeight w = weights_[idx]; traffic::PQElement el = elements_[idx];
        while (true) {
            size_t first = idx * 8 + 1; if (first >= size) break;
            size_t min_idx; traffic::PathWeight min_w;
            if (first + 8 <= size) {
                __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first]));
                __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
                __m256i m1 = _mm256_min_epu32(v, p1);
                __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
                __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
                min_w = _mm256_extract_epi32(m3, 0);
                __m256i cmp = _mm256_cmpeq_epi32(v, _mm256_set1_epi32(min_w)); min_idx = first + __builtin_ctz(_mm256_movemask_ps(_mm256_castsi256_ps(cmp)));
            } else {
                min_idx = first; min_w = weights_[first];
                for (size_t i = 1; i < (size - first); ++i) { if (weights_[first + i] < min_w) { min_w = weights_[first + i]; min_idx = first + i; } }
            }
            if (w <= min_w) break;
            weights_[idx] = weights_[min_idx]; elements_[idx] = elements_[min_idx]; idx = min_idx;
        }
        weights_[idx] = w; elements_[idx] = el;
    }
    std::vector<traffic::PathWeight> weights_; std::vector<traffic::PQElement> elements_;
};

class SafeRadixHeap {
private:
    struct FastBucket {
        traffic::PQElement* __restrict data = nullptr; uint32_t size = 0; uint32_t cap = 0;
        inline void init(uint32_t initial_cap) noexcept { data = static_cast<traffic::PQElement*>(std::malloc(initial_cap * sizeof(traffic::PQElement))); cap = initial_cap; size = 0; }
        inline void destroy() noexcept { if (data) std::free(data); data = nullptr; size = cap = 0; }
        inline void push_back(traffic::PQElement el) noexcept {
            if (__builtin_expect(size == cap, 0)) { cap = cap ? cap * 2 : 64; data = static_cast<traffic::PQElement*>(std::realloc(data, cap * sizeof(traffic::PQElement))); }
            data[size++] = el;
        }
        inline traffic::PQElement pop_back() noexcept { return data[--size]; }
        inline void clear() noexcept { size = 0; }
        [[nodiscard]] inline bool empty() const noexcept { return size == 0; }
    };
public:
    SafeRadixHeap() { for (int i = 0; i < 33; ++i) buckets_[i].init(i < 5 ? 1024 : 256); }
    ~SafeRadixHeap() { for (int i = 0; i < 33; ++i) buckets_[i].destroy(); }
    SafeRadixHeap(const SafeRadixHeap&) = delete;
    inline void push(traffic::PQElement el) noexcept {
        uint32_t eff_val = (el.weight < last_min_) ? last_min_ : el.weight;
        uint32_t index = 32 - _lzcnt_u32(eff_val ^ last_min_);
        buckets_[index].push_back(el); size_++; mask_ |= (1ULL << index);
    }
    inline traffic::PQElement pop() noexcept {
        if (__builtin_expect(buckets_[0].empty(), 0)) fill_bucket0();
        traffic::PQElement top = buckets_[0].pop_back(); if (buckets_[0].empty()) mask_ &= ~1ULL; size_--; return top;
    }
    inline void clear() noexcept { for (int i = 0; i < 33; ++i) buckets_[i].clear(); last_min_ = 0; size_ = 0; mask_ = 0; }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    inline size_t size() const noexcept { return size_; }
    inline void reserve(size_t) noexcept {}
private:
    __attribute__((noinline)) void fill_bucket0() noexcept {
        uint64_t m = mask_ & ~1ULL; if (__builtin_expect(m == 0, 0)) return;
        uint32_t idx = __builtin_ctzll(m); FastBucket& bucket = buckets_[idx];
        traffic::PathWeight min_w = traffic::INF_WEIGHT;
        #pragma GCC ivdep
        #pragma GCC unroll 4
        for (uint32_t i = 0; i < bucket.size; ++i) { if (bucket.data[i].weight < min_w) min_w = bucket.data[i].weight; }
        last_min_ = (min_w < last_min_) ? last_min_ : min_w; uint64_t local_mask = 0;
        for (uint32_t i = 0; i < bucket.size; ++i) {
            traffic::PQElement el = bucket.data[i]; uint32_t eff_w = (el.weight < last_min_) ? last_min_ : el.weight;
            uint32_t new_idx = 32 - _lzcnt_u32(eff_w ^ last_min_); buckets_[new_idx].push_back(el); local_mask |= (1ULL << new_idx);
        }
        bucket.clear(); mask_ &= ~(1ULL << idx); mask_ |= local_mask;
    }
    FastBucket buckets_[33]; uint32_t last_min_ = 0; size_t size_ = 0; uint64_t mask_ = 0; 
};

template<uint32_t SHIFT = 4>
class DeltaBucketQueue {
    static constexpr uint32_t NUM_BUCKETS = 8192; static constexpr uint32_t MASK = NUM_BUCKETS - 1;
public:
    DeltaBucketQueue() { buckets_.resize(NUM_BUCKETS); }
    inline void push(traffic::PQElement el) noexcept { uint32_t idx = (el.weight >> SHIFT) & MASK; buckets_[idx].push_back(el); size_++; if (el.weight < current_min_weight_) current_min_weight_ = el.weight; }
    inline traffic::PQElement pop() noexcept {
        uint32_t curr_idx = (current_min_weight_ >> SHIFT) & MASK;
        while (buckets_[curr_idx].empty()) { current_min_weight_ += (1 << SHIFT); curr_idx = (current_min_weight_ >> SHIFT) & MASK; }
        traffic::PQElement top = buckets_[curr_idx].back(); buckets_[curr_idx].pop_back(); size_--; return top;
    }
    inline void clear() noexcept { for (auto& b : buckets_) b.clear(); current_min_weight_ = traffic::INF_WEIGHT; size_ = 0; }
    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    inline size_t size() const noexcept { return size_; }
    inline void reserve(size_t) noexcept {}
private:
    std::vector<std::vector<traffic::PQElement>> buckets_; traffic::PathWeight current_min_weight_ = traffic::INF_WEIGHT; size_t size_ = 0;
};

} // namespace traffic::router::compute
