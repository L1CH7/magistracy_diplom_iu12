#pragma once

#include <string>
#include <vector>
#include <expected>
#include <cstdint>

namespace traffic::graph_builder
{

struct RamEdge {
    uint32_t from_node;     // Перемапленный индекс
    uint32_t to_node;       // Перемапленный индекс
    float    angle_deg;     // Угол поворота
    uint16_t turn_penalty_sec; // Вычисленный кинематический штраф
    uint16_t static_weight; // Итоговый вес (СТРОГО uint16_t)
};

#pragma pack(push, 1)
struct FlatBVHNode {
    float min_x, min_y, max_x, max_y; // 16 байт
    uint32_t left_child;              // 4 байта (индекс или 0xFFFFFFFF)
    uint32_t right_child;             // 4 байта (индекс или 0xFFFFFFFF)
    uint32_t node_id;                 // 4 байта (для листов - индекс в ram_nodes_)
    uint32_t _padding;                // 4 байта (выравнивание до 32 байт)
};
#pragma pack(pop)

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
