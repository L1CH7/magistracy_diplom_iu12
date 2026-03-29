#pragma once
#include "router/compute/volume_bucket.hpp"
#include <vector>

namespace traffic::router::control {

class VolumeManager {
public:
    explicit VolumeManager(traffic::PointCount num_nodes) : buckets_(num_nodes) {}

    // Доступ для Read-Only горячего цикла Роутера
    [[nodiscard]] const traffic::router::VolumeBucket* data() const noexcept { return buckets_.data(); }

    void book_route(const std::vector<traffic::NodeID>& path, const std::vector<traffic::AbsoluteTime>& etas) noexcept {
        for (size_t i = 0; i < path.size(); ++i) {
            buckets_[path[i]].add_volume(etas[i], 1);
        }
    }

    void unbook_route(const std::vector<traffic::NodeID>& path, const std::vector<traffic::AbsoluteTime>& etas) noexcept {
        for (size_t i = 0; i < path.size(); ++i) {
            buckets_[path[i]].sub_volume(etas[i], 1);
        }
    }

    void advance_time(traffic::AbsoluteTime old_time, traffic::AbsoluteTime new_time) noexcept {
        uint32_t old_idx = (old_time / traffic::router::BUCKET_INTERVAL_SEC) % traffic::router::NUM_BUCKETS;
        uint32_t new_idx = (new_time / traffic::router::BUCKET_INTERVAL_SEC) % traffic::router::NUM_BUCKETS;
        if (old_idx == new_idx) return;

        uint32_t cur = old_idx;
        while (cur != new_idx) {
            for (auto& b : buckets_) {
                b.volumes[cur].store(0, std::memory_order_relaxed);
            }
            cur = (cur + 1) % traffic::router::NUM_BUCKETS;
        }
    }

private:
    std::vector<traffic::router::VolumeBucket> buckets_;
};

} // namespace traffic::router::control
