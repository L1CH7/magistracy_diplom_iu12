#include "db_orchestrator.hpp"
#include "schema.hpp"

#include <iostream>
#include <format>
#include <print>
#include <thread>
#include <chrono>
#include <vector>
#include <utility>
#include <mutex>
#include <atomic>
#include <fstream>
#include <unordered_map>
#include <algorithm>
#include <pqxx/pqxx>
#include "common/thread_pool.hpp"

namespace traffic::graph_builder
{

DbOrchestrator::DbOrchestrator( std::string connection_string )
:   conn_str_( std::move( connection_string ) )
{}

DbOrchestrator::~DbOrchestrator() = default;

void DbOrchestrator::DrawProgressBar( int percent, std::string_view message )
{
    constexpr int bar_width = 50;
    int pos = ( percent * bar_width ) / 100;

    std::string bar;
    for( int i = 0; i < bar_width; ++i )
    {
        if( i < pos )
        {
            bar += "=";
        }
        else if( i == pos )
        {
            bar += ">";
        }
        else
        {
            bar += " ";
        }
    }

    std::print( "\r[{}] {}% {:<50}", bar, percent, message );
    std::cout.flush(); 
}

int64_t DbOrchestrator::GetTableCount( std::string_view table_name )
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        std::string query = std::format( "SELECT count(*) FROM {};", table_name );
        pqxx::result res = work.exec( query );
        return res[ 0 ][ 0 ].as< int64_t >();
    }
    catch( const std::exception & )
    {
        return 0;
    }
}

void DbOrchestrator::ExecuteQuery( std::string_view query_name, std::string_view sql )
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::work work( conn );
        work.exec( sql );
        work.commit();
    }
    catch( const std::exception & e )
    {
        std::println( stderr, "\nDB Error in {}: {}", query_name, e.what() );
        throw;
    }
}

void DbOrchestrator::ExtractCandidates()
{
    std::println( "-> Step 1: Extracting Candidates from osm.ways" );
    ExecuteQuery( "Init Candidate Table", INIT_CANDIDATES_SQL );

    int64_t total_ways = GetTableCount( "osm.ways" );
    if( total_ways == 0 )
    {
        std::println( stderr, "Warning: osm.ways is empty or missing! Are you sure OSM data is imported?" );
    }

    constexpr int batch_size = 50000;
    int offset = 0;
    int total_extracted = 0;

    while( true )
    {
        try
        {
            pqxx::connection conn( conn_str_ );
            pqxx::work work( conn );
            std::string query = std::format( INSERT_CANDIDATES_BATCH_SQL, batch_size, offset );
            pqxx::result res = work.exec( query );
            int inserted = res.affected_rows();
            work.commit();

            total_extracted += inserted;
            offset += inserted;

            int pct = total_ways > 0 ? ( total_extracted * 100 / total_ways ) : 0;
            DrawProgressBar( pct > 100 ? 100 : pct, std::format( "Extracted: {}", total_extracted ) );

            if( inserted < batch_size )
            {
                break;
            }
        }
        catch( const std::exception & e )
        {
            std::println( stderr, "\nExtraction error: {}", e.what() );
            throw;
        }
    }
    DrawProgressBar( 100, "Extract Candidates Complete!" );
    std::println( "" );

    std::println( "-> Indexing Candidates..." );
    ExecuteQuery( "Index Candidates", INDEX_CANDIDATES_SQL );
}

void DbOrchestrator::GridNoding()
{
    std::println( "-> Step 2: Grid-Based Noding Strategy" );
    ExecuteQuery( "Init Merged Table", INIT_MERGED_SQL );

    double min_x = 0.0, min_y = 0.0, max_x = 0.0, max_y = 0.0;
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        work.exec( "SET work_mem = '256MB'" );
        work.exec( "SET synchronous_commit = off" );
        
        pqxx::result res = work.exec( "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent(geom) as e FROM edge_candidates WHERE is_ground = TRUE) t" );
        if( res.empty() || res[ 0 ][ 0 ].is_null() )
        {
            std::println( "No ground edges to node." );
        }
        else
        {
            min_x = res[ 0 ][ 0 ].as< double >();
            min_y = res[ 0 ][ 1 ].as< double >();
            max_x = res[ 0 ][ 2 ].as< double >();
            max_y = res[ 0 ][ 3 ].as< double >();
        }
    }
    catch( const std::exception & e )
    {
        std::println( stderr, "Extent check failed: {}", e.what() );
    }

    if( max_x > min_x )
    {
        double step = 0.05;
        int cols = static_cast< int >( ( max_x - min_x ) / step ) + 1;
        int rows = static_cast< int >( ( max_y - min_y ) / step ) + 1;
        int total_tiles = cols * rows;

        std::println( "Noding Grid: {}x{} = {} tiles (Concurrent workers: {})", cols, rows, total_tiles, std::thread::hardware_concurrency() );

        std::atomic<int> completed_tiles{0};
        std::atomic<int> processed_count{0};
        traffic::core::ThreadPool pool( 0, false, false ); // Без Affinity для билдера
        std::mutex pb_mutex;
        
        int tile_idx = 0;
        for( double cx = min_x; cx < max_x; cx += step )
        {
            for( double cy = min_y; cy < max_y; cy += step )
            {
                int tidx = ++tile_idx;
                pool.Enqueue( [this, cx, cy, step, tidx, total_tiles, &completed_tiles, &processed_count, &pb_mutex]() {
                    std::string query = std::format( GRID_NODING_TILE_SQL, cx, cy, cx + step, cy + step );
                    int affected = 0;
                    try
                    {
                        pqxx::connection conn( conn_str_ );
                        pqxx::work work( conn );
                        pqxx::result res = work.exec( query );
                        affected = res.affected_rows();
                        work.commit();
                    }
                    catch( const std::exception & e )
                    {
                        std::lock_guard<std::mutex> lock(pb_mutex);
                        std::println( stderr, "\nTile {} error: {}", tidx, e.what() );
                    }
                    
                    processed_count += affected;
                    int comp = ++completed_tiles;
                    
                    if (comp % 2 == 0 || comp == total_tiles) {
                        std::lock_guard<std::mutex> lock(pb_mutex);
                        int pct = ( comp * 100 ) / total_tiles;
                        DrawProgressBar( pct, std::format( "Tile {}/{} Nodes: {}", comp, total_tiles, processed_count.load() ) );
                    }
                });
            }
        }
        
        pool.WaitForAll();

        DrawProgressBar( 100, "Grid Noding Complete!" );
        std::println( "" );
    }

    std::println( "-> Copying Bridges and Indexing..." );
    ExecuteQuery( "Copy Bridges", COPY_BRIDGES_SQL );
    ExecuteQuery( "Index Merged", INDEX_MERGED_SQL );
}

void DbOrchestrator::CreateTopology()
{
    std::println( "-> Step 3: Extract Topology (pgr_createTopology)" );
    ExecuteQuery( "Create Topology", CREATE_TOPOLOGY_SQL );
}

void DbOrchestrator::PopulateAttributes()
{
    std::println( "-> Step 4: Map Attributes & Finalize Schema" );
    ExecuteQuery( "Fill Nodes", FILL_NODES_SQL );
    ExecuteQuery( "Fill Edges", FILL_EDGES_SQL );
    ExecuteQuery( "Cleanup Temp Tables", CLEANUP_SQL );
}

void DbOrchestrator::IsolateLCC()
{
    std::println( "-> Step 5: Isolating LCC (Tarjan's connected components algorithm)" );
    DrawProgressBar( 0, "Running pgr_connectedComponents..." );
    ExecuteQuery( "Isolate LCC", ISOLATE_LCC_SQL );
    DrawProgressBar( 100, "Isolated Largest Connected Component!" );
    std::println( "" );
}

void DbOrchestrator::PrintGraphStats()
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        
        pqxx::result res_nodes = work.exec( "SELECT count(*) FROM graphs.nodes;" );
        pqxx::result res_edges = work.exec( "SELECT count(*) FROM graphs.edges;" );
        pqxx::result res_len = work.exec( "SELECT SUM(length_m) / 1000.0 FROM graphs.edges;" );
        
        int64_t nodes = res_nodes[0][0].as< int64_t >();
        int64_t edges = res_edges[0][0].as< int64_t >();
        double len_km = res_len.empty() || res_len[0][0].is_null() ? 0.0 : res_len[0][0].as< double >();
        
        std::println( "\n=== GRAPH STATISTICS ===" );
        std::println( "Nodes: {}", nodes );
        std::println( "Edges: {}", edges );
        std::println( "Total Road Length: {:.2f} km", len_km );
        std::println( "========================" );
    }
    catch( const std::exception & e )
    {
        std::println( stderr, "Stats failed: {}", e.what() );
    }
}

void DbOrchestrator::CalculateLandmarks() {
    std::println("-> (CalculateLandmarks) Placeholder: Requires memory CSR to run Border Minmax + MaxCover.");
}

void DbOrchestrator::DumpCSR() {
    try {
        pqxx::connection conn(conn_str_);
        pqxx::nontransaction work(conn);
        
        DrawProgressBar(0, "Reading nodes from DB...");
        auto nodes_res = work.exec("SELECT id FROM graphs.nodes ORDER BY id");
        std::unordered_map<int64_t, uint32_t> node_map;
        uint32_t dense_id = 0;
        for (auto row : nodes_res) {
            node_map[row[0].as<int64_t>()] = dense_id++;
        }
        uint32_t num_nodes = dense_id;
        
        DrawProgressBar(30, "Reading edges from DB...");
        // duration is length_m / speed_m_s (seconds). source_id/target_id are FK to graphs.nodes.id
        auto edges_res = work.exec(
            "SELECT source_id, target_id, "
            "       ROUND(length_m)::int, "
            "       ROUND(GREATEST(duration, 1))::int "
            "FROM graphs.edges "
            "WHERE source_id IS NOT NULL AND target_id IS NOT NULL "
            "  AND cost > 0"
        );
        
        struct Edge {
            uint32_t src, tgt, length, base_time;
        };
        std::vector<Edge> edges;
        edges.reserve(edges_res.size());
        
        for (auto row : edges_res) {
            auto src_it = node_map.find(row[0].as<int64_t>());
            auto tgt_it = node_map.find(row[1].as<int64_t>());
            if (src_it == node_map.end() || tgt_it == node_map.end()) continue;
            
            edges.push_back({
                src_it->second, tgt_it->second,
                static_cast<uint32_t>(row[2].as<int64_t>()),
                static_cast<uint32_t>(row[3].as<int64_t>())
            });
        }
        uint32_t num_edges = edges.size();
        
        DrawProgressBar(60, "Generating FWD CSR Layout...");
        // Forward Graph
        std::sort(edges.begin(), edges.end(), [](const Edge& a, const Edge& b){
            return a.src < b.src;
        });
        
        std::vector<uint32_t> fwd_row_ptr(num_nodes + 1, 0);
        std::vector<uint32_t> fwd_col_ind(num_edges);
        std::vector<uint32_t> fwd_length(num_edges);
        std::vector<uint32_t> fwd_base_time(num_edges);
        
        for (size_t i = 0; i < num_edges; ++i) {
            fwd_row_ptr[edges[i].src + 1]++;
            fwd_col_ind[i] = edges[i].tgt;
            fwd_length[i] = edges[i].length;
            fwd_base_time[i] = edges[i].base_time;
        }
        for (size_t i = 0; i < num_nodes; ++i) {
            fwd_row_ptr[i + 1] += fwd_row_ptr[i];
        }
        
        DrawProgressBar(80, "Writing csr.bin...");
        {
            std::ofstream out("/app/data/csr.bin", std::ios::binary);
            if (!out) throw std::runtime_error("Could not write /app/data/csr.bin (Hint: did you mount -v ./data:/app/data ?)");
            size_t n = num_nodes, m = num_edges;
            out.write(reinterpret_cast<const char*>(&n), sizeof(n));
            out.write(reinterpret_cast<const char*>(&m), sizeof(m));
            out.write(reinterpret_cast<const char*>(fwd_row_ptr.data()), fwd_row_ptr.size() * sizeof(uint32_t));
            out.write(reinterpret_cast<const char*>(fwd_col_ind.data()), fwd_col_ind.size() * sizeof(uint32_t));
            out.write(reinterpret_cast<const char*>(fwd_length.data()), fwd_length.size() * sizeof(uint32_t));
            out.write(reinterpret_cast<const char*>(fwd_base_time.data()), fwd_base_time.size() * sizeof(uint32_t));
        }

        DrawProgressBar(90, "Writing csr_rev.bin...");
        // Reverse Graph
        std::sort(edges.begin(), edges.end(), [](const Edge& a, const Edge& b){
            return a.tgt < b.tgt;
        });
        
        std::vector<uint32_t> rev_row_ptr(num_nodes + 1, 0);
        std::vector<uint32_t> rev_col_ind(num_edges);
        std::vector<uint32_t> rev_base_time(num_edges);
        
        for (size_t i = 0; i < num_edges; ++i) {
            rev_row_ptr[edges[i].tgt + 1]++;
            rev_col_ind[i] = edges[i].src;
            rev_base_time[i] = edges[i].base_time;
        }
        for (size_t i = 0; i < num_nodes; ++i) {
            rev_row_ptr[i + 1] += rev_row_ptr[i];
        }
        
        {
            std::ofstream rout("/app/data/csr_rev.bin", std::ios::binary);
            if (!rout) throw std::runtime_error("Could not write /app/data/csr_rev.bin");
            size_t n = num_nodes, m = num_edges;
            rout.write(reinterpret_cast<const char*>(&n), sizeof(n));
            rout.write(reinterpret_cast<const char*>(&m), sizeof(m));
            rout.write(reinterpret_cast<const char*>(rev_row_ptr.data()), rev_row_ptr.size() * sizeof(uint32_t));
            rout.write(reinterpret_cast<const char*>(rev_col_ind.data()), rev_col_ind.size() * sizeof(uint32_t));
            rout.write(reinterpret_cast<const char*>(rev_base_time.data()), rev_base_time.size() * sizeof(uint32_t));
        }
        
        DrawProgressBar(100, "CSR Dumps created successfully in /app/data/");
        std::println("");
        
    } catch (const std::exception& e) {
        std::println(stderr, "csr dump: {}", e.what());
    }
}

void DbOrchestrator::DumpAttributes()
{
    // attributes.bin layout (per edge in CSR source-sorted order):
    //   [uint32_t num_edges]
    //   Per edge: [float32 speed_limit_kmh][uint8 lanes][uint8 highway_enum][uint8 oneway][uint8 padding]
    //
    // highway_enum: 0=motorway/trunk, 1=primary/secondary, 2=tertiary, 3=residential/service/other
    try
    {
        pqxx::connection conn(conn_str_);
        pqxx::nontransaction work(conn);

        // Re-build the same source ordering as DumpCSR: sort by source_id, then target_id
        auto res = work.exec(
            "SELECT source_id, target_id, "
            "       COALESCE(speed_limit_kmh, effective_speed_kmh, 60.0), "
            "       COALESCE(lanes, 1), "
            "       highway_type, "
            "       oneway "
            "FROM graphs.edges "
            "WHERE source_id IS NOT NULL AND target_id IS NOT NULL AND cost > 0 "
            "ORDER BY source_id, target_id"
        );

        uint32_t num_edges = res.size();
        DrawProgressBar(0, "Writing attributes.bin...");

        std::ofstream out("/app/data/attributes.bin", std::ios::binary);
        if (!out)
            throw std::runtime_error("Cannot write /app/data/attributes.bin");

        out.write(reinterpret_cast<const char *>(&num_edges), sizeof(num_edges));

        for (auto row : res)
        {
            float speed = static_cast<float>(row[2].as<double>());
            uint8_t lanes = static_cast<uint8_t>(std::min(row[3].as<int>(), 8));

            uint8_t hw = 3;
            if (!row[4].is_null())
            {
                std::string h = row[4].as<std::string>();
                if (h == "motorway" || h == "motorway_link" || h == "trunk" || h == "trunk_link")
                    hw = 0;
                else if (h == "primary" || h == "primary_link" || h == "secondary" || h == "secondary_link")
                    hw = 1;
                else if (h == "tertiary" || h == "tertiary_link")
                    hw = 2;
            }

            uint8_t oneway = row[5].is_null() ? 0 : static_cast<uint8_t>(row[5].as<int>() != 0 ? 1 : 0);
            uint8_t pad = 0;

            out.write(reinterpret_cast<const char *>(&speed), sizeof(speed));
            out.write(reinterpret_cast<const char *>(&lanes), sizeof(lanes));
            out.write(reinterpret_cast<const char *>(&hw), sizeof(hw));
            out.write(reinterpret_cast<const char *>(&oneway), sizeof(oneway));
            out.write(reinterpret_cast<const char *>(&pad), sizeof(pad));
        }

        DrawProgressBar(100, "attributes.bin ready!");
        std::println("");
    }
    catch (const std::exception & e)
    {
        std::println(stderr, "attributes dump: {}", e.what());
    }
}

void DbOrchestrator::DumpRTree()
{
    // r-tree.bin layout (flat packed linear scan structure for Map Matching):
    //
    //   [uint32_t num_entries]  -- one per edge in CSR source-sorted order
    //   Per entry (20 bytes, cache-line friendly 4-pack):
    //     [float32 xmin][float32 ymin][float32 xmax][float32 ymax][uint32_t edge_dense_id]
    //
    // The router's Map Matcher iterates the flat array doing SIMD bbox overlap tests.
    // edge_dense_id is the direct 0-based index into csr.bin row traversal.
    try
    {
        pqxx::connection conn(conn_str_);
        pqxx::nontransaction work(conn);

        // Re-read in the same order as DumpCSR so edge_dense_id matches CSR edge positions
        auto res = work.exec(
            "SELECT "
            "  ST_XMin(geometry), ST_YMin(geometry), "
            "  ST_XMax(geometry), ST_YMax(geometry) "
            "FROM graphs.edges "
            "WHERE source_id IS NOT NULL AND target_id IS NOT NULL AND cost > 0 "
            "ORDER BY source_id, target_id"
        );

        uint32_t num_entries = res.size();
        DrawProgressBar(0, "Writing r-tree.bin (flat BBox entries)...");

        std::ofstream out("/app/data/r-tree.bin", std::ios::binary);
        if (!out)
            throw std::runtime_error("Cannot write /app/data/r-tree.bin");

        out.write(reinterpret_cast<const char *>(&num_entries), sizeof(num_entries));

        for (uint32_t i = 0; i < num_entries; ++i)
        {
            auto row = res[i];
            float xmin = static_cast<float>(row[0].as<double>());
            float ymin = static_cast<float>(row[1].as<double>());
            float xmax = static_cast<float>(row[2].as<double>());
            float ymax = static_cast<float>(row[3].as<double>());

            out.write(reinterpret_cast<const char *>(&xmin), sizeof(xmin));
            out.write(reinterpret_cast<const char *>(&ymin), sizeof(ymin));
            out.write(reinterpret_cast<const char *>(&xmax), sizeof(xmax));
            out.write(reinterpret_cast<const char *>(&ymax), sizeof(ymax));
            out.write(reinterpret_cast<const char *>(&i), sizeof(i));  // edge_dense_id
        }

        DrawProgressBar(100, "r-tree.bin ready!");
        std::println("");
    }
    catch (const std::exception & e)
    {
        std::println(stderr, "r-tree dump: {}", e.what());
    }
}

void DbOrchestrator::SetFlags(bool csr_only, bool recursive, bool overwrite) {
    csr_only_ = csr_only;
    recursive_ = recursive;
    overwrite_ = overwrite;
}

bool DbOrchestrator::IsStageComplete(const std::string& stage) {
    if (overwrite_) return false;
    try {
        pqxx::connection conn(conn_str_);
        pqxx::work work(conn);
        auto res = work.exec_params("SELECT 1 FROM graphs.builder_state WHERE stage = $1", stage);
        return !res.empty();
    } catch (...) { return false; }
}

void DbOrchestrator::RecordStageComplete(const std::string& stage) {
    try {
        pqxx::connection conn(conn_str_);
        pqxx::work work(conn);
        work.exec_params("INSERT INTO graphs.builder_state (stage) VALUES ($1) ON CONFLICT (stage) DO NOTHING", stage);
        work.commit();
    } catch (...) {}
}

void DbOrchestrator::RunPipeline()
{
    std::println( "\n=== TRAFFIC GRAPH BUILDER | PIPELINE START ===" );
    
    try
    {
        bool need_db_build = true;
        if (csr_only_ && !recursive_ && !overwrite_) {
            need_db_build = false;
            // Make sure the schema_initialized step ran (so builder_state exists)
            try {
                pqxx::connection conn(conn_str_);
                pqxx::work work(conn);
                work.exec("SELECT 1 FROM graphs.builder_state LIMIT 1");
            } catch (...) {
                throw std::runtime_error("DB Graph schema missing! Use --recursive to build it.");
            }

            if (!IsStageComplete("lcc_isolated")) {
                throw std::runtime_error("DB Graph is incomplete. Use --recursive to build missing stages.");
            }
        }

        if (need_db_build) {
            pqxx::connection conn( conn_str_ );
            if( !conn.is_open() ) throw std::runtime_error( "Can't open database" );

            if (overwrite_ || !IsStageComplete("schema_initialized")) {
                DrawProgressBar( 0, "Connected to DB. Initializing schema..." );
                ExecuteQuery( "Initialize Schema", DROP_SCHEMA_SQL );
                ExecuteQuery( "Initialize Schema", INIT_SCHEMA_SQL );
                RecordStageComplete("schema_initialized");
                std::println( "\n[Schema initialized]" );
            }

            if (!IsStageComplete("candidates_extracted")) {
                ExtractCandidates();
                RecordStageComplete("candidates_extracted");
            }

            if (!IsStageComplete("grid_noding")) {
                GridNoding();
                RecordStageComplete("grid_noding");
            }

            if (!IsStageComplete("topology_extracted")) {
                CreateTopology();
                RecordStageComplete("topology_extracted");
            }

            if (!IsStageComplete("attributes_mapped")) {
                PopulateAttributes();
                RecordStageComplete("attributes_mapped");
            }

            if (!IsStageComplete("lcc_isolated")) {
                IsolateLCC();
                RecordStageComplete("lcc_isolated");
            }
            
            PrintGraphStats();
        } else {
            std::println( "\n-> DB Graph already exists. Skipping DB Pipeline (CSR only mode)." );
        }

        if (csr_only_ || !need_db_build || overwrite_ || IsStageComplete("lcc_isolated")) {
            std::println( "\n-> Step 6: Calculating ALT Landmarks (Border Minmax + MaxCover Strategy)" );
            CalculateLandmarks();

            std::println( "\n-> Step 7: Dumping CSR Topology (csr.bin, csr_rev.bin)" );
            DumpCSR();

            std::println( "\n-> Step 8: Dumping Edge Attributes (attributes.bin)" );
            DumpAttributes();

            std::println( "\n-> Step 9: Dumping Flat BBox Index for Map Matching (r-tree.bin)" );
            DumpRTree();
        }

        std::println( "\n=== PIPELINE FINISHED SUCCESSFULLY ===" );
    }
    catch( const std::exception & e )
    {
        std::println( stderr, "\nFatal Error during Graph Building: {}", e.what() );
    }
}

} // namespace traffic::graph_builder
