#pragma once
#include "common/graph_types.hpp"
#include <atomic>
#include <vector>

namespace traffic::router {

// Используем макросы из CMake (см. cmake/options.cmake)
constexpr uint32_t BUCKET_INTERVAL_SEC = TRAFFIC_SLOT_SEC;
constexpr uint32_t NUM_BUCKETS = TRAFFIC_NUM_BUCKETS;

struct VolumeBucket {
    std::atomic<traffic::VolumeCount> volumes[NUM_BUCKETS];
    
    VolumeBucket() {
        for (int i = 0; i < NUM_BUCKETS; ++i) {
            volumes[i].store(0, std::memory_order_relaxed);
        }
    }
    
    // Copy constructor and assignment needed for std::vector, but atomics are not copyable
    VolumeBucket(const VolumeBucket& other) {
        for (int i = 0; i < NUM_BUCKETS; ++i) {
            volumes[i].store(other.volumes[i].load(std::memory_order_relaxed), std::memory_order_relaxed);
        }
    }
    
    VolumeBucket& operator=(const VolumeBucket& other) {
        if (this != &other) {
            for (int i = 0; i < NUM_BUCKETS; ++i) {
                volumes[i].store(other.volumes[i].load(std::memory_order_relaxed), std::memory_order_relaxed);
            }
        }
        return *this;
    }

    inline void add_volume(traffic::AbsoluteTime eta, traffic::VolumeCount count) noexcept {
        uint32_t idx = (eta / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        volumes[idx].fetch_add(count, std::memory_order_relaxed);
    }
    
    inline void sub_volume(traffic::AbsoluteTime eta, traffic::VolumeCount count) noexcept {
        uint32_t idx = (eta / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        volumes[idx].fetch_sub(count, std::memory_order_relaxed);
    }
};

class VolumeManager {
public:
    explicit VolumeManager(traffic::PointCount num_nodes) : buckets_(num_nodes) {}

    // Доступ для Read-Only горячего цикла
    [[nodiscard]] const VolumeBucket* data() const noexcept { return buckets_.data(); }

    void advance_time(traffic::AbsoluteTime old_time, traffic::AbsoluteTime new_time) noexcept {
        uint32_t old_idx = (old_time / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        uint32_t new_idx = (new_time / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        if (old_idx == new_idx) return;

        uint32_t cur = old_idx;
        while (cur != new_idx) {
            for (auto& b : buckets_) {
                b.volumes[cur].store(0, std::memory_order_relaxed);
            }
            cur = (cur + 1) % NUM_BUCKETS;
        }
    }
private:
    std::vector<VolumeBucket> buckets_;
};

} // namespace traffic::router
