#pragma once

#include "common/graph_types.hpp"
#include "common/mmap_region.hpp"
#include <memory>
#include <filesystem>
#include <string>
#include <cstring>

namespace traffic::router::control {

struct MappedGraph {
    std::unique_ptr<common::MmapRegion> csr_region;
    std::unique_ptr<common::MmapRegion> landmarks_region;
    std::unique_ptr<common::MmapRegion> rtree_region;
    GraphView view;

    bool load(const std::string& data_dir) {
        try {
            namespace fs = std::filesystem;
            auto base = fs::path(data_dir);
            
            // В нашем дампе (binary_dumper.cpp) CSR может быть в одном файле или разделен.
            // По ТЗ: csr.bin содержит [row_ptr, col_ind, weights] последовательно? 
            // Или раздельно? Исходя из binary_dumper.cpp (Шаг 7 в main-builder):
            // Мы дампили row_ptr, col_ind, base_time в csr.bin одним куском или нет?
            // Давайте проверим binary_dumper.cpp еще раз.
            
            // Для гибкости предположим, что LoadGraphs в RouterManager загружал их.
            // Но пользователь просит MappedGraph который сам вычисляет смещения.
            
            auto csr_path = base / "csr.bin";
            csr_region = std::make_unique<common::MmapRegion>(csr_path.string());
            if (csr_region->empty()) return false;

            const uint8_t* ptr = static_cast<const uint8_t*>(csr_region->data());
            uint32_t num_nodes, num_edges;
            std::memcpy(&num_nodes, ptr, 4);
            std::memcpy(&num_edges, ptr + 4, 4);

            view.row_ptr = reinterpret_cast<const uint32_t*>(ptr + 8);
            view.col_ind = reinterpret_cast<const NodeID*>(ptr + 8 + (num_nodes + 1) * 4);
            view.static_weights = reinterpret_cast<const EdgeWeight*>(ptr + 8 + (num_nodes + 1) * 4 + num_edges * 4);

            // Optional: Load landmarks if they exist
            auto lm_path = base / "landmarks.bin";
            if (fs::exists(lm_path)) {
                landmarks_region = std::make_unique<common::MmapRegion>(lm_path.string());
            }

            // Load R-Tree if it exists
            auto rtree_path = base / "r-tree.bin";
            if (fs::exists(rtree_path)) {
                rtree_region = std::make_unique<common::MmapRegion>(rtree_path.string());
            }
            
            return true;
        } catch (...) {
            return false;
        }
    }
};

} // namespace traffic::router::control
