#pragma once

#include "common/graph_types.hpp"
#include "common/mmap_region.hpp"
#include "common/geometry_store.hpp"
#include <memory>
#include <filesystem>
#include <string>
#include <cstring>

namespace traffic::router::control {

struct MappedGraph {
    std::unique_ptr<traffic::common::MmapRegion> csr_region;
    std::unique_ptr<traffic::common::MmapRegion> landmarks_region;
    std::unique_ptr<traffic::common::MmapRegion> rtree_region;
    std::unique_ptr<traffic::common::GeometryStore> geometry_store;
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
            traffic::NodeID num_nodes;
            traffic::EdgeID num_edges;
            std::memcpy(&num_nodes, ptr, sizeof(num_nodes));
            std::memcpy(&num_edges, ptr + sizeof(num_nodes), sizeof(num_edges));

            size_t header_offset = sizeof(num_nodes) + sizeof(num_edges);
            view.row_ptr = reinterpret_cast<const traffic::EdgeID*>(ptr + header_offset);
            view.col_ind = reinterpret_cast<const traffic::NodeID*>(ptr + header_offset + (num_nodes + 1) * sizeof(traffic::EdgeID));
            view.static_weights = reinterpret_cast<const traffic::EdgeWeight*>(ptr + header_offset + (num_nodes + 1) * sizeof(traffic::EdgeID) + num_edges * sizeof(traffic::NodeID));

            // Optional: Load landmarks if they exist
            auto lm_path = base / "landmarks.bin";
            if (fs::exists(lm_path)) {
                landmarks_region = std::make_unique<common::MmapRegion>(lm_path.string());
            }

            // Load R-Tree if it exists
            auto rtree_path = base / "r-tree.bin";
            if (fs::exists(rtree_path)) {
                rtree_region = std::make_unique<traffic::common::MmapRegion>(rtree_path.string());
            }

            // Load Geometry Store if it exists
            auto geom_path = base / "geometry_flat.bin";
            if (fs::exists(geom_path)) {
                geometry_store = std::make_unique<traffic::common::GeometryStore>();
                if (!geometry_store->load(geom_path.string())) {
                    geometry_store.reset();
                }
            }
            
            return true;
        } catch (...) {
            return false;
        }
    }
};

} // namespace traffic::router::control
