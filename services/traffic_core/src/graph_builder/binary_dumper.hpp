#pragma once

#include <string>
#include <vector>
#include <expected>
#include <cstdint>
#include "common/graph_types.hpp"

namespace traffic::graph_builder
{

// RamEdge и RamNode используют типы из graph_types.hpp
struct RamEdge {
    traffic::EdgeID from_node;     // Перемапленный индекс (eb_node_id)
    traffic::EdgeID to_node;       // Перемапленный индекс (eb_node_id)
    float    angle_deg;     // Угол поворота
    traffic::EdgeWeight turn_penalty_sec; // Вычисленный кинематический штраф
    traffic::EdgeWeight static_weight;    // Итоговый вес (eb_edge_weight)
};

// FlatBVHNode теперь берется из ../common/graph_types.hpp

struct RamNode {
    int64_t orig_db_id;
    float length_m;
    float speed_kmh;
    float t_free_base;
    int32_t k_magic;
    uint32_t morton_code;
    uint8_t  highway_class; // 0=motorway, 1=primary, 2=tertiary, 3=residential
    uint8_t lanes;
    uint8_t oneway;
    
    // BBox для Z-кривой и будущего R-Tree
    float min_x, min_y, max_x, max_y;

    // Геометрия (WKB)
    std::vector<uint8_t> wkb_geom;
};

class BinaryDumper {
public:
    explicit BinaryDumper(std::string connection_string);
    ~BinaryDumper();

    std::expected<void, std::string> LoadAndSortNodes(); 
    std::expected<void, std::string> DumpExtendedAttributes(); // ВМЕСТО DumpAttributes
    std::expected<void, std::string> DumpCSR();
    std::expected<void, std::string> DumpKMagic();
    std::expected<void, std::string> DumpRTree();

private:
    std::string conn_str_;
    std::vector<RamNode> ram_nodes_; 
    std::vector<RamEdge> ram_edges_; // МАНЕВРЫ
};

} // namespace traffic::graph_builder
