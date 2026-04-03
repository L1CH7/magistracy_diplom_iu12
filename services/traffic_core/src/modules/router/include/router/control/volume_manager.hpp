#pragma once
#include "router/compute/volume_bucket.hpp"
#include <vector>
#include <span>

namespace traffic::router::control {

class VolumeManager {
public:
    explicit VolumeManager(traffic::PointCount num_nodes) : buckets_(num_nodes) {}

    // Доступ для Read-Only горячего цикла Роутера
    [[nodiscard]] const traffic::router::compute::VolumeBucket* data() const noexcept { return buckets_.data(); }

    void book_route(std::span<const traffic::EdgeID> path, std::span<const traffic::AbsoluteTime> etas, traffic::VolumeCount count = 1) noexcept {
        for (size_t i = 0; i < path.size(); ++i) {
            buckets_[path[i]].add_volume(etas[i], count);
        }
    }

    void unbook_route(std::span<const traffic::EdgeID> path, std::span<const traffic::AbsoluteTime> etas, traffic::VolumeCount count = 1) noexcept {
        for (size_t i = 0; i < path.size(); ++i) {
            buckets_[path[i]].sub_volume(etas[i], count);
        }
    }

    void advance_time(traffic::AbsoluteTime old_time, traffic::AbsoluteTime new_time) noexcept {
        uint32_t old_idx = (old_time / traffic::router::compute::BUCKET_INTERVAL_SEC) % traffic::router::compute::NUM_BUCKETS;
        uint32_t new_idx = (new_time / traffic::router::compute::BUCKET_INTERVAL_SEC) % traffic::router::compute::NUM_BUCKETS;
        if (old_idx == new_idx) return;

        uint32_t cur = old_idx;
        while (cur != new_idx) {
            for (auto& b : buckets_) {
                b.volumes[cur].store(0, std::memory_order_relaxed);
            }
            cur = (cur + 1) % traffic::router::compute::NUM_BUCKETS;
        }
    }

private:
    std::vector<traffic::router::compute::VolumeBucket> buckets_;
};

} // namespace traffic::router::control
