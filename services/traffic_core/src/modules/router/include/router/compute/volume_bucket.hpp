#pragma once
#include "common/graph_types.hpp"
#include <atomic>

namespace traffic::router::compute {

// Используем макросы из CMake (см. cmake/options.cmake)
constexpr uint32_t BUCKET_INTERVAL_SEC = TRAFFIC_SLOT_SEC;
constexpr uint32_t NUM_BUCKETS = TRAFFIC_NUM_BUCKETS;

struct VolumeBucket {
    std::atomic<traffic::VolumeCount> volumes[NUM_BUCKETS];
    
    VolumeBucket() {
        for (int i = 0; i < NUM_BUCKETS; ++i) volumes[i].store(0, std::memory_order_relaxed);
    }
    
    VolumeBucket(const VolumeBucket& other) {
        for (int i = 0; i < NUM_BUCKETS; ++i) 
            volumes[i].store(other.volumes[i].load(std::memory_order_relaxed), std::memory_order_relaxed);
    }
    
    VolumeBucket& operator=(const VolumeBucket& other) {
        if (this != &other) {
            for (int i = 0; i < NUM_BUCKETS; ++i) 
                volumes[i].store(other.volumes[i].load(std::memory_order_relaxed), std::memory_order_relaxed);
        }
        return *this;
    }

    inline void add_volume(traffic::AbsoluteTime eta, traffic::VolumeCount count) noexcept {
        uint32_t idx = (eta / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        volumes[idx].fetch_add(count, std::memory_order_relaxed);
    }
    
    inline void sub_volume(traffic::AbsoluteTime eta, traffic::VolumeCount count) noexcept {
        uint32_t idx = (eta / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        traffic::VolumeCount old_val = volumes[idx].load(std::memory_order_relaxed);

        // Безопасное вычитание с clamp до 0
        while (old_val >= count) {
            if (volumes[idx].compare_exchange_weak(old_val, old_val - count, std::memory_order_relaxed)) {
                return;
            }
        }

        // Если в корзинке осталось меньше, чем мы хотим вычесть (из-за advance_time), просто обнуляем её
        while (old_val > 0) {
            if (volumes[idx].compare_exchange_weak(old_val, 0, std::memory_order_relaxed)) {
                return;
            }
        }
    }
};

} // namespace traffic::router::compute
