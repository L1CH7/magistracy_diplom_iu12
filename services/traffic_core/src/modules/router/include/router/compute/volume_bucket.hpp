#pragma once

#include "types.hpp"
#include <atomic>

namespace traffic::router {

// Жестко закодированные константы планирования времени (DoD)
constexpr TimeSec BUCKET_INTERVAL_SEC = 300; // 5 минут на одну корзинку
constexpr uint32_t NUM_BUCKETS = 288;        // 24 часа = 288 пятиминуток

// Структура резервирования емкости ребра
// ALIGN_CACHE_LINE устраняет False Sharing между рабочими потоками 
// (каждое ребро лежит в отдельной или нескольких целых кэш-линиях ОЗУ).
struct ALIGN_CACHE_LINE VolumeBucket {
    std::atomic<uint16_t> volumes[NUM_BUCKETS];

    VolumeBucket() {
        for (uint32_t i = 0; i < NUM_BUCKETS; ++i) {
            volumes[i].store(0, std::memory_order_relaxed);
        }
    }

    // Запрет копирования ради безопасности атомарных элементов
    VolumeBucket(const VolumeBucket&) = delete;
    VolumeBucket& operator=(const VolumeBucket&) = delete;

    // Перемещение для std::vector
    VolumeBucket(VolumeBucket&& other) noexcept {
        for (uint32_t i = 0; i < NUM_BUCKETS; ++i) {
            volumes[i].store(other.volumes[i].load(std::memory_order_relaxed), std::memory_order_relaxed);
        }
    }

    // Lock-Free резервирование (Router -> predict)
    inline void add_volume(TimeSec time_of_entry, uint16_t amount) noexcept {
        uint32_t bucket_idx = (time_of_entry / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        volumes[bucket_idx].fetch_add(amount, std::memory_order_relaxed);
    }

    // Lock-Free уменьшение (Simulator -> fact correction)
    inline void sub_volume(TimeSec time_of_entry, uint16_t amount) noexcept {
        uint32_t bucket_idx = (time_of_entry / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        uint16_t current = volumes[bucket_idx].load(std::memory_order_relaxed);
        // Защита от underflow 
        while (current >= amount && !volumes[bucket_idx].compare_exchange_weak(current, current - amount, std::memory_order_relaxed)) {
            // Spinlock retry if interrupted
        }
        if (current < amount) {
            volumes[bucket_idx].store(0, std::memory_order_relaxed);
        }
    }

    // Быстрое Lock-Free чтение (LERP/BPR Engine)
    [[nodiscard]] inline uint16_t get_volume(TimeSec time_of_entry) const noexcept {
        uint32_t bucket_idx = (time_of_entry / BUCKET_INTERVAL_SEC) % NUM_BUCKETS;
        return volumes[bucket_idx].load(std::memory_order_relaxed);
    }
};

} // namespace traffic::router
