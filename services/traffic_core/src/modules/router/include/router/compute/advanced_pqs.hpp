#pragma once
#include <vector>
#include <limits>
#include <immintrin.h>
#include <x86intrin.h>
#include <cstdint>
#include <algorithm>
#include "router/compute/priority_queue.hpp"

namespace traffic::router::compute {

/**
 * @brief VECTOR RADIX HEAP: The absolute champion. 
 * Fully branchless index calculation using hardware LZCNT.
 */
class VectorRadixHeap {
public:
    VectorRadixHeap() {
        for (auto& b : buckets_) b.reserve(512);
    }

    inline void push(traffic::PQElement el) noexcept {
        uint32_t index = get_bucket_index(el.weight);
        buckets_[index].push_back(el);
        size_++;
        mask_ |= (1ULL << index);
    }

    inline traffic::PQElement pop() noexcept {
        if (buckets_[0].empty()) fill_bucket0();
        traffic::PQElement top = buckets_[0].back();
        buckets_[0].pop_back();
        if (buckets_[0].empty()) mask_ &= ~1ULL;
        size_--;
        return top;
    }

    inline void clear() noexcept {
        for (auto& b : buckets_) b.clear();
        last_min_ = 0;
        size_ = 0;
        mask_ = 0;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }
    inline void reserve(size_t) noexcept {}

private:
    [[nodiscard]] inline uint32_t get_bucket_index(uint32_t val) const noexcept {
        // Zero-Branching: _lzcnt_u32(0) == 32. Therefore 32 - 32 == 0.
        return 32 - _lzcnt_u32(val ^ last_min_);
    }

    void fill_bucket0() noexcept {
        uint64_t m = mask_ & ~1ULL;
        if (m == 0) return;
        uint32_t idx = __builtin_ctzll(m);
        auto& bucket = buckets_[idx];

        traffic::PathWeight min_w = bucket[0].weight;
        for (const auto& el : bucket) {
            min_w = (el.weight < min_w) ? el.weight : min_w;
        }
        last_min_ = min_w;

        for (const auto& el : bucket) {
            uint32_t new_idx = get_bucket_index(el.weight);
            buckets_[new_idx].push_back(el);
            mask_ |= (1ULL << new_idx);
        }
        bucket.clear();
        mask_ &= ~(1ULL << idx);
    }

    std::vector<traffic::PQElement> buckets_[33];
    uint32_t last_min_ = 0;
    size_t size_ = 0;
    uint64_t mask_ = 0; 
};

/**
 * @brief FLAT RADIX HEAP: Zero dynamic allocations.
 * Includes Software Prefetching (_mm_prefetch) to hide pointer-chasing latency.
 */
class FlatRadixHeap {
    static constexpr uint32_t NULL_IDX = 0xFFFFFFFF;

public:
    FlatRadixHeap() {
        data_.reserve(1000000);
        next_.reserve(1000000);
        clear();
    }

    inline void push(traffic::PQElement el) noexcept {
        uint32_t idx = get_bucket_index(el.weight);
        uint32_t node_ptr = free_head_++;
        
        if (node_ptr >= data_.size()) {
            data_.push_back(el);
            next_.push_back(heads_[idx]);
        } else {
            data_[node_ptr] = el;
            next_[node_ptr] = heads_[idx];
        }
        
        heads_[idx] = node_ptr;
        size_++;
        mask_ |= (1ULL << idx);
    }

    inline traffic::PQElement pop() noexcept {
        if (heads_[0] == NULL_IDX) fill_bucket0();
        
        uint32_t node_ptr = heads_[0];
        traffic::PQElement el = data_[node_ptr];
        heads_[0] = next_[node_ptr];
        if (heads_[0] == NULL_IDX) mask_ &= ~1ULL;
        size_--;
        return el;
    }

    inline void clear() noexcept {
        std::fill(heads_, heads_ + 33, NULL_IDX);
        data_.clear();
        next_.clear();
        last_min_ = 0;
        size_ = 0;
        mask_ = 0;
        free_head_ = 0;
    }

    [[nodiscard]] inline bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] inline size_t size() const noexcept { return size_; }
    inline void reserve(size_t cap) noexcept {
        data_.reserve(cap);
        next_.reserve(cap);
    }

private:
    [[nodiscard]] inline uint32_t get_bucket_index(uint32_t val) const noexcept {
        return 32 - _lzcnt_u32(val ^ last_min_);
    }

    void fill_bucket0() noexcept {
        uint64_t m = mask_ & ~1ULL;
        if (m == 0) return;
        uint32_t idx = __builtin_ctzll(m);
        
        uint32_t curr = heads_[idx];
        traffic::PQElement min_el = data_[curr];
        uint32_t it = next_[curr];
        
        while (it != NULL_IDX) {
            // Hide pointer-chasing latency
            _mm_prefetch(reinterpret_cast<const char*>(&data_[next_[it]]), _MM_HINT_T0);
            if (data_[it].weight < min_el.weight) min_el = data_[it];
            it = next_[it];
        }
        last_min_ = min_el.weight;

        curr = heads_[idx];
        heads_[idx] = NULL_IDX;
        mask_ &= ~(1ULL << idx);

        while (curr != NULL_IDX) {
            uint32_t nxt = next_[curr];
            uint32_t new_idx = get_bucket_index(data_[curr].weight);
            next_[curr] = heads_[new_idx];
            heads_[new_idx] = curr;
            mask_ |= (1ULL << new_idx);
            curr = nxt;
        }
    }

    std::vector<traffic::PQElement> data_;
    std::vector<uint32_t> next_;
    uint32_t heads_[33];
    uint32_t last_min_ = 0;
    uint32_t free_head_ = 0;
    size_t size_ = 0;
    uint64_t mask_ = 0;
};

/**
 * @brief TRUE SIMD 8-ARY HEAP: SoA Memory Layout
 * Uses AVX2 horizontal minimum to find the smallest child in O(1) instructions.
 */
class Simd8AryHeap {
public:
    Simd8AryHeap() {
        weights_.reserve(1000000);
        ids_.reserve(1000000);
        weights_.push_back(0); // 1-based indexing
        ids_.push_back(0);
    }

    inline void push(traffic::PQElement el) noexcept {
        size_t idx = weights_.size();
        weights_.push_back(el.weight);
        ids_.push_back(el.id);
        sift_up(idx);
    }

    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = {weights_[1], ids_[1]};
        weights_[1] = weights_.back();
        ids_[1] = ids_.back();
        weights_.pop_back();
        ids_.pop_back();
        if (weights_.size() > 1) sift_down(1);
        return top;
    }

    inline void clear() noexcept {
        weights_.clear(); ids_.clear();
        weights_.push_back(0); ids_.push_back(0);
    }

    [[nodiscard]] inline bool empty() const noexcept { return weights_.size() <= 1; }
    [[nodiscard]] inline size_t size() const noexcept { return weights_.size() - 1; }
    inline void reserve(size_t cap) noexcept {
        weights_.reserve(cap + 1);
        ids_.reserve(cap + 1);
    }

private:
    void sift_up(size_t idx) noexcept {
        traffic::PathWeight val_w = weights_[idx];
        traffic::NodeID val_id = ids_[idx];
        while (idx > 1) {
            size_t parent = (idx + 6) / 8;
            if (val_w >= weights_[parent]) break;
            weights_[idx] = weights_[parent];
            ids_[idx] = ids_[parent];
            idx = parent;
        }
        weights_[idx] = val_w;
        ids_[idx] = val_id;
    }

    void sift_down(size_t idx) noexcept {
        const size_t n = weights_.size();
        traffic::PathWeight val_w = weights_[idx];
        traffic::NodeID val_id = ids_[idx];
        
        while (true) {
            size_t child_base = (idx - 1) * 8 + 2;
            if (child_base >= n) break;

            size_t min_idx;
            traffic::PathWeight min_w;

            size_t remaining = n - child_base;
            if (remaining >= 8) {
                // TRUE AVX2 FAST PATH: Load 8 continuous weights (32 bytes)
                __m256i w = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[child_base]));
                
                // Horizontal Min over 8x uint32
                __m256i perm = _mm256_permute2x128_si256(w, w, 1);
                __m256i m1 = _mm256_min_epu32(w, perm);
                __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
                __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
                uint32_t min_val = _mm256_extract_epi32(m3, 0);

                // Find index of the minimum value
                __m256i min_vec = _mm256_set1_epi32(min_val);
                __m256i cmp = _mm256_cmpeq_epi32(w, min_vec);
                uint32_t mask = _mm256_movemask_ps(_mm256_castsi256_ps(cmp));
                
                min_idx = child_base + __builtin_ctz(mask);
                min_w = min_val;
            } else {
                // SCALAR FALLBACK: For the very last incomplete leaf node
                min_idx = child_base;
                min_w = weights_[child_base];
                for (size_t i = 1; i < remaining; ++i) {
                    if (weights_[child_base + i] < min_w) {
                        min_w = weights_[child_base + i];
                        min_idx = child_base + i;
                    }
                }
            }

            if (val_w <= min_w) break;
            weights_[idx] = weights_[min_idx];
            ids_[idx] = ids_[min_idx];
            idx = min_idx;
        }
        weights_[idx] = val_w;
        ids_[idx] = val_id;
    }

    std::vector<traffic::PathWeight> weights_;
    std::vector<traffic::NodeID> ids_;
};

} // namespace traffic::router::compute
