#include "binary_dumper.hpp"
#include "road_config.hpp"
#include <pqxx/pqxx>
#include <print>
#include <format>
#include <fstream>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <stdexcept>
#include <cstdint>
#include <cmath>
#include <numeric>

namespace traffic::graph_builder
{

namespace
{
void DrawProgressBar( int percent, std::string_view message )
{
    constexpr int bar_width = 50;
    int filled = bar_width * percent / 100;
    std::string bar( filled, '=' );
    if( filled < bar_width )
        bar += '>';
    bar.resize( bar_width, ' ' );
    std::print( "\r[{}] {}% {:<50}", bar, percent, message );
    std::fflush( stdout );
}

// Вспомогательные функции для Z-кривой
inline uint32_t ExpandBits(uint32_t v) {
    v = (v | (v << 8)) & 0x00FF00FF;
    v = (v | (v << 4)) & 0x0F0F0F0F;
    v = (v | (v << 2)) & 0x33333333;
    v = (v | (v << 1)) & 0x55555555;
    return v;
}

inline uint32_t CalculateMortonCode(float x, float y, float min_x, float min_y, float max_x, float max_y) {
    float nx = std::clamp((x - min_x) / (max_x - min_x), 0.0f, 1.0f);
    float ny = std::clamp((y - min_y) / (max_y - min_y), 0.0f, 1.0f);
    uint32_t ix = static_cast<uint32_t>(nx * 65535.0f);
    uint32_t iy = static_cast<uint32_t>(ny * 65535.0f);
    return (ExpandBits(ix) | (ExpandBits(iy) << 1));
}
}

BinaryDumper::BinaryDumper( std::string connection_string )
:   conn_str_( std::move( connection_string ) )
{}

BinaryDumper::~BinaryDumper() = default;

std::expected<void, std::string> BinaryDumper::LoadAndSortNodes() {
    try {
        DrawProgressBar(0, "Loading eb_nodes into RAM (with WKB)...");
        pqxx::connection conn(conn_str_);
        pqxx::nontransaction work(conn);

        // ST_AsBinary(geom) для получения WKB
        auto node_res = work.exec(
            "SELECT id, length_m, speed_kmh, t_free, lanes, highway, oneway, "
            "ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom), "
            "ST_AsBinary(geom) "
            "FROM graphs.eb_nodes"
        );

        ram_nodes_.reserve(node_res.size());
        float global_min_x = 180.0f, global_min_y = 90.0f;
        float global_max_x = -180.0f, global_max_y = -90.0f;

        for (auto row : node_res) {
            RamNode n;
            n.orig_db_id = row[0].template as<int64_t>();
            n.length_m   = row[1].template as<float>();
            n.speed_kmh  = row[2].template as<float>();
            n.t_free_base = row[3].template as<float>();
            n.lanes      = static_cast<uint8_t>(std::min(row[4].template as<int>(), 8));
            
            std::string hw = row[5].is_null() ? "" : row[5].template as<std::string>();
            const auto& config = GetRoadConfig(hw);
            
            n.highway_class = 3; 
            if (hw == "motorway" || hw == "trunk" || hw == "motorway_link") n.highway_class = 0;
            else if (hw == "primary" || hw == "secondary" || hw == "primary_link") n.highway_class = 1;
            else if (hw == "tertiary" || hw == "tertiary_link") n.highway_class = 2;

            n.oneway = row[6].is_null() ? 0 : static_cast<uint8_t>(row[6].template as<int>());
            
            n.min_x = row[7].template as<float>(); n.min_y = row[8].template as<float>();
            n.max_x = row[9].template as<float>(); n.max_y = row[10].template as<float>();

            if (n.min_x < global_min_x) global_min_x = n.min_x;
            if (n.min_y < global_min_y) global_min_y = n.min_y;
            if (n.max_x > global_max_x) global_max_x = n.max_x;
            if (n.max_y > global_max_y) global_max_y = n.max_y;

            // Расчет K_magic (Fixed-Point Math)
            float v_free = EffectiveSpeedKmh(n.speed_kmh, config.default_speed_kmh);
            float c_300 = static_cast<float>(config.default_lanes) * 150.0f;
            if (c_300 <= 0.0f) c_300 = 150.0f;
            
            float t_f = std::max(n.t_free_base, 1.0f);
            double k_magic_base_f = (t_f * ((v_free / 5.0f) - 1.0f)) / (c_300 * c_300) * K_MAGIC_SHIFT;
            if (k_magic_base_f <= 0.0) k_magic_base_f = 10.0;
            
            n.k_magic = static_cast<int32_t>(std::floor(k_magic_base_f));

            if (!row[11].is_null()) {
                auto wkb_field = row[11].template as<pqxx::binarystring>();
                n.wkb_geom.assign(wkb_field.begin(), wkb_field.end());
            }

            ram_nodes_.push_back(std::move(n));
        }

        DrawProgressBar(40, "Topological Reordering (Z-Curve)...");
        for (auto& n : ram_nodes_) {
            float cx = (n.min_x + n.max_x) * 0.5f;
            float cy = (n.min_y + n.max_y) * 0.5f;
            n.morton_code = CalculateMortonCode(cx, cy, global_min_x, global_min_y, global_max_x, global_max_y);
        }

        std::sort(ram_nodes_.begin(), ram_nodes_.end(), [](const RamNode& a, const RamNode& b) {
            return a.morton_code < b.morton_code;
        });

        // Создаем карту старый ID -> новый Dense ID
        std::unordered_map<int64_t, uint32_t> id_map;
        id_map.reserve(ram_nodes_.size());
        for (uint32_t i = 0; i < ram_nodes_.size(); ++i) {
            id_map[ram_nodes_[i].orig_db_id] = i;
        }

        DrawProgressBar(70, "Loading eb_edges (maneuvers) & Kinematics...");
        auto edge_res = work.exec(
            "SELECT from_eb_node, to_eb_node, turn_angle "
            "FROM graphs.eb_edges"
        );

        ram_edges_.reserve(edge_res.size());
        for (auto row : edge_res) {
            int64_t from_orig = row[0].as<int64_t>();
            int64_t to_orig   = row[1].as<int64_t>();
            
            auto it_from = id_map.find(from_orig);
            auto it_to   = id_map.find(to_orig);
            if (it_from == id_map.end() || it_to == id_map.end()) continue;

            RamEdge e;
            e.from_node = it_from->second;
            e.to_node   = it_to->second;
            e.angle_deg = row[2].is_null() ? 0.0f : row[2].as<float>();

            // Кинематический расчет штрафа + дефолты из конфига
            float v1_ms = ram_nodes_[e.from_node].speed_kmh / 3.6f;
            float v2_ms = ram_nodes_[e.to_node].speed_kmh / 3.6f;
            if (v1_ms < 1.0f) v1_ms = 1.0f;
            if (v2_ms < 1.0f) v2_ms = 1.0f;

            float R = (ram_nodes_[e.from_node].highway_class == 0) ? 50.0f : 15.0f;
            float v_turn_ms = std::min({v1_ms, v2_ms, std::sqrt(MU_FRICTION * G_ACCEL * R)});
            v_turn_ms = std::max(v_turn_ms, 1.3f); 

            float angle_rad = std::abs(e.angle_deg) * static_cast<float>(M_PI) / 180.0f;
            float t_ideal = (R * angle_rad) / v1_ms;
            float t_real = ((v1_ms - v_turn_ms) / DECEL_MS2) + 
                           ((R * angle_rad) / v_turn_ms) + 
                           ((v2_ms - v_turn_ms) / ACCEL_MS2);

            float kinematic_penalty = std::max(0.0f, t_real - t_ideal);
            
            // Находим конфиг для целевого типа дороги
            std::string target_hw = ""; // В этом этапе у нас только класс
            // Для простоты используем кинематику, но накидываем за разворот
            float penalty = kinematic_penalty;
            if (std::abs(e.angle_deg) > 150.0f) penalty += 15.0f; // Разворот дороже

            e.turn_penalty_sec = static_cast<uint16_t>(std::round(penalty));
            uint32_t total_weight = static_cast<uint32_t>(std::round(ram_nodes_[e.to_node].t_free_base + penalty));
            e.static_weight = total_weight;

            ram_edges_.push_back(std::move(e));
        }

        // ШАГ: ЧЕК-СУММА (Простая версия: count + max_id)
        auto node_check = work.exec("SELECT count(*), max(id) FROM graphs.eb_nodes");
        auto edge_check = work.exec("SELECT count(*), max(id) FROM graphs.eb_edges");
        
        std::ofstream v_out("/app/data/version.bin", std::ios::binary);
        if (v_out) {
            int64_t n_cnt = node_check[0][0].template as<int64_t>();
            int64_t n_max = node_check[0][1].template as<int64_t>();
            int64_t e_cnt = edge_check[0][0].template as<int64_t>();
            int64_t e_max = edge_check[0][1].template as<int64_t>();
            v_out.write(reinterpret_cast<const char*>(&n_cnt), 8);
            v_out.write(reinterpret_cast<const char*>(&n_max), 8);
            v_out.write(reinterpret_cast<const char*>(&e_cnt), 8);
            v_out.write(reinterpret_cast<const char*>(&e_max), 8);
        }

        DrawProgressBar(100, "In-Memory Graph Prepared.");
        std::println("");
        return {};
    } catch (const std::exception& e) {
        return std::unexpected(std::format("LoadAndSortNodes failed: {}", e.what()));
    }
}


std::expected<void, std::string> BinaryDumper::DumpCSR()
{
    if (ram_nodes_.empty()) return std::unexpected("RAM nodes are empty. Call LoadAndSortNodes first.");

    try {
        uint32_t num_nodes = static_cast<uint32_t>(ram_nodes_.size());
        uint32_t num_edges = static_cast<uint32_t>(ram_edges_.size());

        DrawProgressBar(0, "Generating FWD CSR layout from RAM...");
        std::vector<uint32_t> fwd_row_ptr(num_nodes + 1, 0);
        std::vector<uint32_t> fwd_col_ind(num_edges);
        std::vector<uint16_t> fwd_base_time(num_edges);

        for (const auto& e : ram_edges_)
            fwd_row_ptr[e.from_node + 1]++;
        for (uint32_t i = 0; i < num_nodes; ++i)
            fwd_row_ptr[i + 1] += fwd_row_ptr[i];

        {
            std::vector<uint32_t> cur = fwd_row_ptr;
            for (const auto& e : ram_edges_) {
                uint32_t pos = cur[e.from_node]++;
                fwd_col_ind[pos] = e.to_node;
                fwd_base_time[pos] = e.static_weight;
            }
        }

        DrawProgressBar(50, "Writing csr.bin...");
        {
            std::ofstream out("/app/data/csr.bin", std::ios::binary);
            if (!out) return std::unexpected("Cannot write /app/data/csr.bin");
            out.write(reinterpret_cast<const char*>(&num_nodes), 4);
            out.write(reinterpret_cast<const char*>(&num_edges), 4);
            out.write(reinterpret_cast<const char*>(fwd_row_ptr.data()), fwd_row_ptr.size() * 4);
            out.write(reinterpret_cast<const char*>(fwd_col_ind.data()), fwd_col_ind.size() * 4);
            out.write(reinterpret_cast<const char*>(fwd_base_time.data()), fwd_base_time.size() * sizeof(uint16_t));
        }

        DrawProgressBar(75, "Generating REV CSR layout from RAM...");
        std::vector<uint32_t> rev_row_ptr(num_nodes + 1, 0);
        std::vector<uint32_t> rev_col_ind(num_edges);
        std::vector<uint16_t> rev_base_time(num_edges);

        for (const auto& e : ram_edges_)
            rev_row_ptr[e.to_node + 1]++;
        for (uint32_t i = 0; i < num_nodes; ++i)
            rev_row_ptr[i + 1] += rev_row_ptr[i];

        {
            std::vector<uint32_t> cur = rev_row_ptr;
            for (const auto& e : ram_edges_) {
                uint32_t pos = cur[e.to_node]++;
                rev_col_ind[pos] = e.from_node;
                rev_base_time[pos] = e.static_weight;
            }
        }

        DrawProgressBar(90, "Writing csr_rev.bin...");
        {
            std::ofstream rout("/app/data/csr_rev.bin", std::ios::binary);
            if (!rout) return std::unexpected("Cannot write /app/data/csr_rev.bin");
            rout.write(reinterpret_cast<const char*>(&num_nodes), 4);
            rout.write(reinterpret_cast<const char*>(&num_edges), 4);
            rout.write(reinterpret_cast<const char*>(rev_row_ptr.data()), rev_row_ptr.size() * 4);
            rev_row_ptr.clear(); 
            rout.write(reinterpret_cast<const char*>(rev_col_ind.data()), rev_col_ind.size() * 4);
            rout.write(reinterpret_cast<const char*>(rev_base_time.data()), rev_base_time.size() * sizeof(uint16_t));
        }

        DrawProgressBar(100, "CSR (FWD/REV) ready from RAM!");
        std::println("");
        return {};
    } catch (const std::exception& e) {
        return std::unexpected(std::format("DumpCSR failed: {}", e.what()));
    }
}

std::expected<void, std::string> BinaryDumper::DumpExtendedAttributes() {
    try {
        if (ram_nodes_.empty()) return std::unexpected("RAM nodes are empty. Call LoadAndSortNodes first.");
        
        uint32_t num_nodes = static_cast<uint32_t>(ram_nodes_.size());
        uint32_t num_edges = static_cast<uint32_t>(ram_edges_.size());

        DrawProgressBar(0, "Writing extended attributes (attributes.bin)...");
        std::ofstream out_attr("/app/data/attributes.bin", std::ios::binary);
        if (!out_attr) return std::unexpected("Cannot write /app/data/attributes.bin");

        // Хедер
        out_attr.write(reinterpret_cast<const char*>(&num_nodes), sizeof(num_nodes));
        out_attr.write(reinterpret_cast<const char*>(&num_edges), sizeof(num_edges));

        // Дамп узлов
        for (const auto& n : ram_nodes_) {
            uint8_t pad = 0;
            out_attr.write(reinterpret_cast<const char*>(&n.speed_kmh), sizeof(n.speed_kmh));
            out_attr.write(reinterpret_cast<const char*>(&n.lanes), sizeof(n.lanes));
            out_attr.write(reinterpret_cast<const char*>(&n.highway_class), sizeof(n.highway_class));
            out_attr.write(reinterpret_cast<const char*>(&n.oneway), sizeof(n.oneway));
            out_attr.write(reinterpret_cast<const char*>(&pad), sizeof(pad));
            out_attr.write(reinterpret_cast<const char*>(&n.length_m), sizeof(n.length_m));
            out_attr.write(reinterpret_cast<const char*>(&n.t_free_base), sizeof(n.t_free_base));
            out_attr.write(reinterpret_cast<const char*>(&n.k_magic), sizeof(n.k_magic));
            out_attr.write(reinterpret_cast<const char*>(&n.min_x), sizeof(n.min_x));
            out_attr.write(reinterpret_cast<const char*>(&n.min_y), sizeof(n.min_y));
        }

        // Дамп маневров
        for (const auto& e : ram_edges_) {
            out_attr.write(reinterpret_cast<const char*>(&e.from_node), sizeof(e.from_node));
            out_attr.write(reinterpret_cast<const char*>(&e.to_node), sizeof(e.to_node));
            out_attr.write(reinterpret_cast<const char*>(&e.turn_penalty_sec), sizeof(e.turn_penalty_sec));
            out_attr.write(reinterpret_cast<const char*>(&e.static_weight), sizeof(e.static_weight));
        }
        out_attr.close();

        DrawProgressBar(50, "Writing flat geometry (geometry_flat.bin)...");
        std::ofstream out_geom("/app/data/geometry_flat.bin", std::ios::binary);
        if (!out_geom) return std::unexpected("Cannot write /app/data/geometry_flat.bin");

        std::vector<uint32_t> geom_offsets;
        geom_offsets.reserve(num_nodes + 1);
        std::vector<float> all_coords;
        all_coords.reserve(num_nodes * 10); // Эвристика

        uint32_t current_offset = 0;
        for (const auto& n : ram_nodes_) {
            geom_offsets.push_back(current_offset);
            if (n.wkb_geom.size() < 13) continue; // Минимум Линейка

            // Простеший парсер WKB (LineString)
            // byte_order(1), type(4), count(4)
            uint32_t pt_count = 0;
            std::memcpy(&pt_count, &n.wkb_geom[5], 4);
            
            const double* pts = reinterpret_cast<const double*>(&n.wkb_geom[9]);
            for (uint32_t i = 0; i < pt_count; ++i) {
                all_coords.push_back(static_cast<float>(pts[i*2]));   // x
                all_coords.push_back(static_cast<float>(pts[i*2+1])); // y
            }
            current_offset += pt_count;
        }
        geom_offsets.push_back(current_offset);

        uint32_t total_points = static_cast<uint32_t>(all_coords.size() / 2);
        out_geom.write(reinterpret_cast<const char*>(&num_nodes), sizeof(num_nodes));
        out_geom.write(reinterpret_cast<const char*>(&total_points), sizeof(total_points));
        out_geom.write(reinterpret_cast<const char*>(geom_offsets.data()), geom_offsets.size() * sizeof(uint32_t));
        out_geom.write(reinterpret_cast<const char*>(all_coords.data()), all_coords.size() * sizeof(float));

        DrawProgressBar(100, "Extended attributes and geometry ready!");
        std::println("");
        return {};
    } catch (const std::exception& e) {
        return std::unexpected(std::format("DumpExtendedAttributes failed: {}", e.what()));
    }
}

std::expected<void, std::string> BinaryDumper::DumpKMagic() {
    try {
        if (ram_nodes_.empty()) return std::unexpected("RAM nodes are empty.");
        DrawProgressBar(0, "Writing k_magic.bin...");

        std::ofstream out("/app/data/k_magic.bin", std::ios::binary);
        if (!out) return std::unexpected("Cannot write k_magic.bin");

        for (const auto& n : ram_nodes_) {
            out.write(reinterpret_cast<const char*>(&n.k_magic), sizeof(n.k_magic));
        }

        DrawProgressBar(100, "k_magic.bin ready!");
        std::println("");
        return {};
    } catch (const std::exception& e) {
        return std::unexpected(std::format("DumpKMagic failed: {}", e.what()));
    }
}

std::expected<void, std::string> BinaryDumper::DumpRTree() {
    try {
        if (ram_nodes_.empty()) return std::unexpected("RAM nodes are empty.");
        DrawProgressBar(0, "Building BVH R-Tree in RAM...");

        std::vector<FlatBVHNode> bvh_tree;
        bvh_tree.reserve(ram_nodes_.size() * 2); // Резерв для бинарного дерева

        // Массив индексов для сортировки при построении дерева
        std::vector<uint32_t> indices(ram_nodes_.size());
        std::iota(indices.begin(), indices.end(), 0);

        // Рекурсивная лямбда построения BVH
        auto build_bvh = [&ram_nodes = ram_nodes_, &indices, &bvh_tree](this auto& self, uint32_t start, uint32_t end) -> uint32_t {
            uint32_t node_idx = static_cast<uint32_t>(bvh_tree.size());
            bvh_tree.push_back(FlatBVHNode{});
            FlatBVHNode& node = bvh_tree[node_idx];
            node.left_child = 0xFFFFFFFF;
            node.right_child = 0xFFFFFFFF;
            node.node_id = 0xFFFFFFFF;
            node._padding = 0;

            // Считаем BBox текущего кластера
            node.min_x = 180.0f; node.min_y = 90.0f;
            node.max_x = -180.0f; node.max_y = -90.0f;
            for (uint32_t i = start; i < end; ++i) {
                const auto& n = ram_nodes[indices[i]];
                if (n.min_x < node.min_x) node.min_x = n.min_x;
                if (n.min_y < node.min_y) node.min_y = n.min_y;
                if (n.max_x > node.max_x) node.max_x = n.max_x;
                if (n.max_y > node.max_y) node.max_y = n.max_y;
            }

            uint32_t count = end - start;
            if (count == 1) {
                // Лист
                node.node_id = indices[start];
                return node_idx;
            }

            // Находим самую длинную ось для сплита
            float span_x = node.max_x - node.min_x;
            float span_y = node.max_y - node.min_y;
            int axis = (span_x > span_y) ? 0 : 1;

            // Сортируем индексы по центру выбранной оси
            std::sort(indices.begin() + start, indices.begin() + end, [&](uint32_t a, uint32_t b) {
                const auto& na = ram_nodes[a];
                const auto& nb = ram_nodes[b];
                if (axis == 0) return (na.min_x + na.max_x) < (nb.min_x + nb.max_x);
                return (na.min_y + na.max_y) < (nb.min_y + nb.max_y);
            });

            uint32_t mid = start + count / 2;
            uint32_t left_child = self(start, mid);
            uint32_t right_child = self(mid, end);

            // ВАЖНО: ссылки могут инвалидироваться при push_back, поэтому переполучаем node
            bvh_tree[node_idx].left_child = left_child;
            bvh_tree[node_idx].right_child = right_child;

            return node_idx;
        };

        DrawProgressBar(30, "Splitting Bounding Boxes...");
        build_bvh(0, static_cast<uint32_t>(indices.size()));

        DrawProgressBar(70, "Writing r-tree.bin...");
        std::ofstream out("/app/data/r-tree.bin", std::ios::binary);
        if (!out) return std::unexpected("Cannot write r-tree.bin");

        uint32_t total_nodes = static_cast<uint32_t>(bvh_tree.size());
        out.write(reinterpret_cast<const char*>(&total_nodes), sizeof(total_nodes));
        out.write(reinterpret_cast<const char*>(bvh_tree.data()), bvh_tree.size() * sizeof(FlatBVHNode));

        DrawProgressBar(100, "In-Memory BVH R-Tree generated!");
        std::println("");
        return {};
    } catch (const std::exception& e) {
        return std::unexpected(std::format("DumpRTree failed: {}", e.what()));
    }
}

} // namespace traffic::graph_builder
