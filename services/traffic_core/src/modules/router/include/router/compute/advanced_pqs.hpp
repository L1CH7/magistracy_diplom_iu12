#pragma once
#include <chrono>
#include <immintrin.h>
#include <cstdint>
#include <cstdlib>
#include <algorithm>
#include <cassert>
#include <cstring>
#include <bit>
#include <vector>
#include "common/graph_types.hpp"
#include "router/compute/priority_queue.hpp"
#include "router/compute/quick_heap.hpp"

namespace traffic::router::compute {

namespace details {
    /**
     * @brief АКАДЕМИЧЕСКАЯ СПРАВКА: Key-Index Packing для SIMD-оптимизации многоарных куч.
     * 
     * В классических многоарных (d-ary) кучах операция извлечения минимума (pop) требует поиска 
     * минимального потомка среди d кандидатов. При использовании SIMD-инструкций (SSE/AVX2) 
     * поиск минимального значения выполняется за O(log d) векторных шагов, однако нахождение его 
     * индекса (позиции) требует выполнения ресурсоемких инструкций:
     *   1) Векторного сравнения на равенство (_mm256_cmpeq_epi32)
     *   2) Получения битовой маски (_mm256_movemask_ps)
     *   3) Сканирования битов (__builtin_ctz / tzcnt)
     * 
     * Эти операции создают длинную цепочку зависимостей по данным (data dependency chain) длиной 
     * 18-20 тактов CPU, что блокирует конвейер Out-of-Order Execution и мешает спекулятивной загрузке 
     * потомков на следующем уровне (Pointer Chasing).
     * 
     * Данный шаблон KeyIndexPacking реализует упаковку относительного индекса (0..Arity-1) в младшие 
     * биты ключа (PathWeight). Сдвиг реального веса влево на Shift бит:
     *   - Для 4-арной кучи: сдвиг на 2 бита (маска 3)
     *   - Для 8-арной кучи: сдвиг на 3 бита (маска 7)
     *   - Для 16-арной кучи: сдвиг на 4 бита (маска 15)
     * 
     * Поскольку индекс первого потомка для родителя p равен (Arity * p + 1), младшие биты абсолютного 
     * индекса любого потомка idx автоматически соответствуют его относительной позиции [0..Arity-1] 
     * в векторном регистре. При поиске минимума редукция возвращает упакованное значение, из которого 
     * вес и индекс извлекаются за 0 тактов (через сдвиг и маску), полностью исключая cmpeq/movemask/ctz 
     * из критического пути выполнения.
     */
    template<uint32_t Arity>
    struct KeyIndexPacking {
        static constexpr uint32_t Shift = (Arity == 4) ? 2 : ((Arity == 8) ? 3 : 4);
        static constexpr uint32_t Mask = Arity - 1;
        
        static inline traffic::PathWeight encode(traffic::PathWeight w, uint32_t idx) noexcept {
            return (w << Shift) | (idx ? ((idx - 1) & Mask) : 0);
        }
        
        static inline traffic::PathWeight decode_weight(traffic::PathWeight ew) noexcept {
            return ew >> Shift;
        }
        
        static inline uint32_t decode_index(traffic::PathWeight ew) noexcept {
            return ew & Mask;
        }
        
        static inline traffic::PathWeight update_index(traffic::PathWeight ew, uint32_t idx) noexcept {
            return (ew & ~Mask) | (idx ? ((idx - 1) & Mask) : 0);
        }
    };
}

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
        traffic::PathWeight ew = el.weight << 3;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 3;
            if ((weights_[p] >> 3) <= el.weight) break;
            weights_[idx] = (weights_[p] & ~7) | ((idx - 1) & 7);
            elements_[idx] = elements_[p];
            idx = p;
        }
        weights_[idx] = ew | (idx ? ((idx - 1) & 7) : 0);
        elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { weights_[0] = 0xFFFFFFFF; return top; }
        traffic::PathWeight lw = weights_[size_] >> 3; 
        traffic::PQElement le = elements_[size_]; 
        weights_[size_] = 0xFFFFFFFF;
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
            uint32_t min_combined = _mm256_extract_epi32(m3, 0);
            
            uint32_t min_w = min_combined >> 3;
            if (lw <= min_w) break;
            
            uint32_t local_idx = min_combined & 7;
            uint32_t min_idx = first + local_idx;
            _mm_prefetch(reinterpret_cast<const char*>(&weights_[(min_idx << 3) + 1]), _MM_HINT_T0);
            weights_[idx] = (weights_[min_idx] & ~7) | (idx ? ((idx - 1) & 7) : 0);
            elements_[idx] = elements_[min_idx];
            idx = min_idx;
        }
        weights_[idx] = (lw << 3) | (idx ? ((idx - 1) & 7) : 0);
        elements_[idx] = le;
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
        traffic::PathWeight ew = el.weight << 3;
        while (idx > 0) {
            uint32_t p = (idx - 1) >> 3;
            if ((weights_[p] >> 3) <= el.weight) break;
            weights_[idx] = (weights_[p] & ~7) | ((idx - 1) & 7);
            elements_[idx] = elements_[p];
            idx = p;
        }
        weights_[idx] = ew | (idx ? ((idx - 1) & 7) : 0);
        elements_[idx] = el;
    }
    inline traffic::PQElement pop() noexcept {
        traffic::PQElement top = elements_[0];
        if (__builtin_expect(--size_ == 0, 0)) { return top; }
        traffic::PathWeight lw = weights_[size_] >> 3; 
        traffic::PQElement le = elements_[size_];
        uint32_t idx = 0;
        
        while (true) {
            uint32_t first = (idx << 3) + 1;
            if (__builtin_expect(first >= size_, 0)) break;
            
            __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(&weights_[first]));
            
            if (first + 8 > size_) {
                const __m256i v_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
                const __m256i inf = _mm256_set1_epi32(0xFFFFFFFF);
                const __m256i v_size = _mm256_set1_epi32(size_);
                __m256i v_first = _mm256_set1_epi32(first);
                __m256i v_indices = _mm256_add_epi32(v_first, v_offsets);
                __m256i mask = _mm256_cmpgt_epi32(v_size, v_indices);
                v = _mm256_blendv_epi8(inf, v, mask);
            }
            
            __m256i p1 = _mm256_permute2x128_si256(v, v, 1);
            __m256i m1 = _mm256_min_epu32(v, p1);
            __m256i m2 = _mm256_min_epu32(m1, _mm256_shuffle_epi32(m1, _MM_SHUFFLE(1, 0, 3, 2)));
            __m256i m3 = _mm256_min_epu32(m2, _mm256_shuffle_epi32(m2, _MM_SHUFFLE(2, 3, 0, 1)));
            uint32_t min_combined = _mm256_extract_epi32(m3, 0);
            
            uint32_t min_w = min_combined >> 3;
            if (lw <= min_w) break;
            
            uint32_t local_idx = min_combined & 7;
            uint32_t min_idx = first + local_idx;
            _mm_prefetch(reinterpret_cast<const char*>(&weights_[(min_idx << 3) + 1]), _MM_HINT_T0);
            weights_[idx] = (weights_[min_idx] & ~7) | (idx ? ((idx - 1) & 7) : 0);
            elements_[idx] = elements_[min_idx];
            idx = min_idx;
        }
        weights_[idx] = (lw << 3) | (idx ? ((idx - 1) & 7) : 0);
        elements_[idx] = le;
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
        if (sz_ > 0 && mw_ != 0xFFFFFFFF) {
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
        if (sz_ > 0 && mw_ != 0xFFFFFFFF) {
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

/**
 * @brief Вектор с выравниванием по границе 64 байт для эффективных SIMD-операций.
 * 
 * Класс выделяет выровненную память и исключает накладные расходы 
 * на инициализацию элементов при изменении размера.
 * Имена методов с маленькой буквы необходимы для совместимости с алгоритмами STL.
 */
class alignas( 64 ) AlignedVector
{
public:
    AlignedVector()
    :   data_( nullptr ),
        size_( 0 ),
        capacity_( 0 )
    {}

    ~AlignedVector()
    {
        if( data_ != nullptr )
        {
            std::free( data_ );
        }
    }

    AlignedVector( const AlignedVector & ) = delete;
    AlignedVector & operator=( const AlignedVector & ) = delete;

    AlignedVector( AlignedVector && other ) noexcept
    :   data_( other.data_ ),
        size_( other.size_ ),
        capacity_( other.capacity_ )
    {
        other.data_ = nullptr;
        other.size_ = 0;
        other.capacity_ = 0;
    }

    AlignedVector & operator=( AlignedVector && other ) noexcept
    {
        if( this != &other )
        {
            if( data_ != nullptr )
            {
                std::free( data_ );
            }
            data_ = other.data_;
            size_ = other.size_;
            capacity_ = other.capacity_;
            other.data_ = nullptr;
            other.size_ = 0;
            other.capacity_ = 0;
        }
        return *this;
    }

    inline void reserve( size_t cap ) noexcept
    {
        if( cap <= capacity_ )
        {
            return;
        }

        size_t new_cap = ( cap + 7 ) & ~7;
        uint64_t * new_data = static_cast< uint64_t * >( std::aligned_alloc( 64, new_cap * sizeof( uint64_t ) ) );
        if( size_ > 0 && data_ != nullptr )
        {
            std::memcpy( new_data, data_, size_ * sizeof( uint64_t ) );
        }
        if( data_ != nullptr )
        {
            std::free( data_ );
        }
        data_ = new_data;
        capacity_ = new_cap;
    }

    inline void clear() noexcept
    {
        size_ = 0;
    }

    [[nodiscard]] inline size_t size() const noexcept
    {
        return size_;
    }

    [[nodiscard]] inline bool empty() const noexcept
    {
        return size_ == 0;
    }

    inline void push_back( uint64_t val ) noexcept
    {
        if( size_ >= capacity_ )
        {
            reserve( capacity_ == 0 ? 16 : capacity_ * 2 );
        }
        data_[ size_++ ] = val;
    }

    inline void pop_back() noexcept
    {
        --size_;
    }

    [[nodiscard]] inline uint64_t back() const noexcept
    {
        return data_[ size_ - 1 ];
    }

    inline void resize_no_init( size_t new_size ) noexcept
    {
        size_ = new_size;
    }

    [[nodiscard]] inline uint64_t * data() noexcept
    {
        return data_;
    }

    [[nodiscard]] inline const uint64_t * data() const noexcept
    {
        return data_;
    }

    inline uint64_t & operator[]( size_t idx ) noexcept
    {
        return data_[ idx ];
    }

    inline const uint64_t & operator[]( size_t idx ) const noexcept
    {
        return data_[ idx ];
    }

    [[nodiscard]] inline uint64_t * begin() noexcept
    {
        return data_;
    }

    [[nodiscard]] inline const uint64_t * begin() const noexcept
    {
        return data_;
    }

    [[nodiscard]] inline uint64_t * end() noexcept
    {
        return data_ + size_;
    }

    [[nodiscard]] inline const uint64_t * end() const noexcept
    {
        return data_ + size_;
    }

    inline void insert( uint64_t * pos, uint64_t val ) noexcept
    {
        size_t idx = pos - data_;
        if( size_ >= capacity_ )
        {
            reserve( capacity_ == 0 ? 16 : capacity_ * 2 );
        }
        std::memmove( data_ + idx + 1, data_ + idx, ( size_ - idx ) * sizeof( uint64_t ) );
        data_[ idx ] = val;
        size_++;
    }

private:
    uint64_t * data_ = nullptr;
    size_t size_ = 0;
    size_t capacity_ = 0;
};

/**
 * @brief Очередь с приоритетом SimdQuickHeap на C++ с использованием AVX2.
 * Оптимизирована для небольших очередей (до ~2048 элементов).
 */
class alignas( 64 ) SimdQuickHeapQueue
{
public:
    SimdQuickHeapQueue()
    {
        pivots_.reserve( 32 );
        buckets_.resize( 32 );
        for( auto & bucket : buckets_ )
        {
            bucket.reserve( 128 );
        }
    }

    ~SimdQuickHeapQueue() = default;

    SimdQuickHeapQueue( const SimdQuickHeapQueue & ) = delete;
    SimdQuickHeapQueue & operator=( const SimdQuickHeapQueue & ) = delete;

    /**
     * @brief Резервирует память для предотвращения динамических аллокаций.
     */
    inline void reserve( size_t cap ) noexcept
    {
        pivots_.reserve( 32 );
        if( buckets_.size() < 32 )
        {
            buckets_.resize( 32 );
        }
        for( auto & bucket : buckets_ )
        {
            bucket.reserve( cap + 4 );
        }
    }

    /**
     * @brief Очищает только те бакеты, которые реально содержали элементы.
     */
    inline void clear() noexcept
    {
        size_t active_buckets = pivots_.size() + 1;
        if( active_buckets > buckets_.size() )
        {
            active_buckets = buckets_.size();
        }
        for( size_t i = 0; i < active_buckets; ++i )
        {
            buckets_[ i ].clear();
        }
        pivots_.clear();
        size_ = 0;
    }

    /**
     * @brief Проверяет, пуста ли очередь.
     */
    [[nodiscard]] inline bool empty() const noexcept
    {
        return size_ == 0;
    }

    /**
     * @brief Возвращает количество элементов в очереди.
     */
    [[nodiscard]] inline size_t size() const noexcept
    {
        return size_;
    }

    /**
     * @brief Вставляет элемент в очередь.
     */
    inline void push( traffic::PQElement el ) noexcept
    {
        uint64_t val = ( static_cast< uint64_t >( el.weight ) << 32 ) | el.id;
        size_t target_layer = push_position( val );
        if( target_layer >= buckets_.size() )
        {
            buckets_.resize( target_layer + 1 );
        }
        auto & bucket = buckets_[ target_layer ];
        if( SORT && target_layer == pivots_.size() && bucket.size() < N )
        {
            auto it = std::lower_bound( bucket.begin(), bucket.end(), val, std::greater< uint64_t >() );
            bucket.insert( it, val );
        }
        else
        {
            bucket.push_back( val );
        }
        size_++;
    }

    /**
     * @brief Извлекает минимальный элемент из очереди.
     */
    inline traffic::PQElement pop() noexcept
    {
        size_t layer = pivots_.size();
        if( layer == 0 && buckets_[ 0 ].empty() )
        {
            return traffic::PQElement{};
        }
        if( buckets_[ layer ].size() > N )
        {
            while( buckets_[ pivots_.size() ].size() > N )
            {
                partition();
            }
            if( SORT )
            {
                auto & last_bucket = buckets_[ pivots_.size() ];
                if( last_bucket.size() <= 16 )
                {
                    insertion_sort_greater( last_bucket );
                }
                else
                {
                    std::sort( last_bucket.begin(), last_bucket.end(), std::greater< uint64_t >() );
                }
            }
        }
        auto & last_bucket = buckets_[ pivots_.size() ];
        uint64_t val = last_bucket.back();
        last_bucket.pop_back();

        if( last_bucket.empty() && pivots_.size() > 0 )
        {
            pivots_.pop_back();
            if( SORT && buckets_[ pivots_.size() ].size() <= N )
            {
                auto & prev_bucket = buckets_[ pivots_.size() ];
                if( prev_bucket.size() <= 16 )
                {
                    insertion_sort_greater( prev_bucket );
                }
                else
                {
                    std::sort( prev_bucket.begin(), prev_bucket.end(), std::greater< uint64_t >() );
                }
            }
        }
        size_--;
        traffic::PQElement el;
        el.weight = static_cast< traffic::PathWeight >( val >> 32 );
        el.id = static_cast< traffic::NodeID >( val & 0xFFFFFFFF );
        return el;
    }

private:
    static constexpr size_t N = 16;
    static constexpr bool SORT = true;

    std::vector< uint64_t > pivots_;
    std::vector< AlignedVector > buckets_;
    size_t size_ = 0;

    /**
     * @brief Быстрая сортировка вставками по убыванию для малых массивов.
     */
    static inline void insertion_sort_greater( AlignedVector & vec ) noexcept
    {
        size_t n = vec.size();
        for( size_t i = 1; i < n; ++i )
        {
            uint64_t key = vec[ i ];
            int64_t j = static_cast< int64_t >( i ) - 1;
            while( j >= 0 && vec[ j ] < key )
            {
                vec[ j + 1 ] = vec[ j ];
                --j;
            }
            vec[ j + 1 ] = key;
        }
    }

    /**
     * @brief Находит индекс слоя для вставки элемента с использованием быстрых проверок границ и бинарного поиска.
     */
    inline size_t push_position( uint64_t t ) const noexcept
    {
        size_t n = pivots_.size();
        if( n == 0 )
        {
            return 0;
        }
        if( t <= pivots_.back() )
        {
            return n;
        }
        if( t > pivots_.front() )
        {
            return 0;
        }

        auto it = std::lower_bound( pivots_.begin(), pivots_.end(), t, std::greater< uint64_t >() );
        return std::distance( pivots_.begin(), it );
    }

    /**
     * @brief Разделяет текущий слой на два с использованием высокоэффективного branchless алгоритма.
     */
    inline void partition() noexcept
    {
        size_t layer = pivots_.size();
        if( layer + 1 >= buckets_.size() )
        {
            buckets_.resize( layer + 2 );
        }
        auto & cur_bucket = buckets_[ layer ];
        auto & next_bucket = buckets_[ layer + 1 ];
        size_t n = cur_bucket.size();

        uint64_t pivot = 0;
        size_t pivot_pos = 0;
        size_t mid = n / 2;
        uint64_t a = cur_bucket[ 0 ];
        uint64_t b = cur_bucket[ mid ];
        uint64_t c = cur_bucket[ n - 1 ];

        if( ( a <= b && b <= c ) || ( c <= b && b <= a ) )
        {
            pivot = b;
            pivot_pos = mid;
        }
        else if( ( b <= a && a <= c ) || ( c <= a && a <= b ) )
        {
            pivot = a;
            pivot_pos = 0;
        }
        else
        {
            pivot = c;
            pivot_pos = n - 1;
        }

        pivots_.push_back( pivot );
        next_bucket.clear();

        cur_bucket.reserve( n );
        next_bucket.reserve( n );

        size_t cur_len = 0;
        size_t next_len = 0;

        for( size_t i = 0; i < n; ++i )
        {
            uint64_t val = cur_bucket[ i ];
            if( i == pivot_pos )
            {
                cur_bucket[ cur_len++ ] = val;
                continue;
            }

            bool keep = ( val > pivot ) || ( val == pivot && i < pivot_pos );
            cur_bucket[ cur_len ] = val;
            next_bucket[ next_len ] = val;

            cur_len += keep;
            next_len += !keep;
        }

        cur_bucket.resize_no_init( cur_len );
        next_bucket.resize_no_init( next_len );

        if( cur_len == 0 )
        {
            std::swap( cur_bucket, next_bucket );
            pivots_.pop_back();
        }
    }
};

using Strict8ArySoAHeap = Strict8ArySoAEagerHeap;

using Ultimate4AryHeap = Strict4AryHeap;
using Ultimate8AryHeap = Strict8ArySoALazyHeap;
using Ultimate8ArySoAHeap = Strict8ArySoAEagerHeap;
using Branchless4AryHeap = Strict4AryHeap;
using SoA8AryAvx2Heap = Strict8ArySoAEagerHeap;

} // namespace traffic::router::compute
