#pragma once
#include <vector>
#include <algorithm>
#include "common/graph_types.hpp"

namespace traffic::router {

/**
 * @brief Branchless 4-ary Heap for high-performance priority queue operations.
 */
class PriorityQueue {
public:
    inline void push(traffic::PQElement element) {
        heap_.push_back(element);
        sift_up(heap_.size() - 1);
    }

    inline traffic::PQElement pop() {
        traffic::PQElement top = heap_.front();
        heap_.front() = heap_.back();
        heap_.pop_back();
        if (!heap_.empty()) {
            sift_down(0);
        }
        return top;
    }

    inline void clear() { heap_.clear(); }
    inline bool empty() const { return heap_.empty(); }
    inline size_t size() const { return heap_.size(); }
    inline void reserve(size_t capacity) { heap_.reserve(capacity); }

private:
    inline void sift_up(size_t idx) {
        traffic::PQElement val = heap_[idx];
        while (idx > 0) {
            size_t parent = (idx - 1) / 4;
            if (heap_[parent].weight <= val.weight) break;
            heap_[idx] = heap_[parent];
            idx = parent;
        }
        heap_[idx] = val;
    }

    inline void sift_down(size_t idx) {
        const size_t size = heap_.size();
        traffic::PQElement val = heap_[idx];

        while (true) {
            size_t first_child = idx * 4 + 1;
            if (first_child >= size) break;

            size_t min_child = first_child;
            traffic::PathWeight min_weight = heap_[first_child].weight;

            #pragma GCC unroll 3
            for (size_t offset = 1; offset < 4; ++offset) {
                size_t child_idx = first_child + offset;
                bool valid = (child_idx < size);
                traffic::PathWeight cw = valid ? heap_[child_idx].weight : traffic::INF_WEIGHT;
                
                bool is_less = (cw < min_weight);
                min_weight = is_less ? cw : min_weight;
                min_child  = is_less ? child_idx : min_child;
            }

            if (__builtin_expect(val.weight <= min_weight, 0)) break;

            heap_[idx] = heap_[min_child];
            idx = min_child;
        }
        heap_[idx] = val;
    }

private:
    std::vector<traffic::PQElement> heap_;
};

} // namespace traffic::router
