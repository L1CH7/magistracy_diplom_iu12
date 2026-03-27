#include "sql_orchestrator.hpp"
#include "schema.hpp"
#include "common/thread_pool.hpp"

#include <pqxx/pqxx>
#include <print>
#include <format>
#include <string>
#include <algorithm>
#include <stdexcept>
#include <atomic>
#include <thread>
#include <mutex>
#include <vector>
#include <algorithm>

namespace traffic::graph_builder
{

namespace
{
std::mutex g_io_mutex;

void DrawProgressBar( int percent, std::string_view message )
{
    std::lock_guard<std::mutex> lock( g_io_mutex );
    constexpr int bar_width = 50;
    int filled = bar_width * percent / 100;
    std::string bar( filled, '=' );
    if( filled < bar_width )
        bar += '>';
    bar.resize( bar_width, ' ' );
    std::print( "\r[{}] {}% {:<50}", bar, percent, message );
    std::fflush( stdout );
}
} // namespace

SqlOrchestrator::SqlOrchestrator( std::string connection_string )
:   conn_str_( std::move( connection_string ) )
{}

SqlOrchestrator::~SqlOrchestrator() = default;

void SqlOrchestrator::ExecuteQuery( std::string_view query_name, std::string_view sql )
{
    pqxx::connection conn( conn_str_ );
    pqxx::work       work( conn );
    work.exec( sql );
    work.commit();
}

int64_t SqlOrchestrator::GetTableCount( std::string_view table_name )
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        auto res = work.exec( std::format( "SELECT COUNT(*) FROM {}", table_name ) );
        return res[ 0 ][ 0 ].as<int64_t>();
    }
    catch( ... )
    {
        return 0;
    }
}

std::expected<void, std::string> SqlOrchestrator::InitializeSchema()
{
    try
    {
        DrawProgressBar( 0, "Initializing schema..." );
        ExecuteQuery( "Drop Schema", std::string( DROP_SCHEMA_SQL ) );
        ExecuteQuery( "Init Schema", std::string( INIT_SCHEMA_SQL ) );
        std::println( "\n[Schema initialized]" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "InitializeSchema failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::ExtractCandidates()
{
    try
    {
        std::println( "\n-> Step 1: Extracting Candidates from osm.ways" );

        pqxx::connection conn( conn_str_ );
        pqxx::work       work( conn );

        work.exec( INIT_CANDIDATES_SQL );
        work.commit();

        int64_t total = GetTableCount( "osm.ways" );
        constexpr int64_t batch_size = 100000;
        int64_t offset = 0;

        while( true )
        {
            pqxx::connection batch_conn( conn_str_ );
            pqxx::work batch_work( batch_conn );

            std::string sql = std::vformat( INSERT_CANDIDATES_BATCH_SQL, 
                                            std::make_format_args( batch_size, offset ) );
            auto res = batch_work.exec( sql );
            batch_work.commit();

            if( res.affected_rows() == 0 ) break;

            offset += batch_size;
            int pct = static_cast<int>( std::min( offset * 100 / std::max( total, 1L ), 100L ) );
            DrawProgressBar( pct, "Extract Candidates..." );
        }

        ExecuteQuery( "Index Candidates", std::string( INDEX_CANDIDATES_SQL ) );
        DrawProgressBar( 100, "Extract Candidates Complete!" );
        std::println( "" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "ExtractCandidates failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::GridNoding()
{
    try
    {
        std::println( "\n-> Step 2: Grid-Based Noding Strategy" );

        ExecuteQuery( "Init Merged", std::string( INIT_MERGED_SQL ) );

        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction stat( conn );
        auto bbox_res = stat.exec(
            "SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) "
            "FROM (SELECT ST_Extent(geom) AS b FROM graphs.edge_candidates) AS t" );

        if( bbox_res.empty() || bbox_res[ 0 ][ 0 ].is_null() )
        {
            std::println( "-> No candidates found. Skipping Grid Noding." );
            return {};
        }

        double xmin = bbox_res[ 0 ][ 0 ].as<double>();
        double ymin = bbox_res[ 0 ][ 1 ].as<double>();
        double xmax = bbox_res[ 0 ][ 2 ].as<double>();
        double ymax = bbox_res[ 0 ][ 3 ].as<double>();

        const int grid_x = 14;
        const int grid_y = 12;
        double dx = ( xmax - xmin ) / grid_x;
        double dy = ( ymax - ymin ) / grid_y;

        unsigned int num_workers = std::max( 1u, std::thread::hardware_concurrency() );
        std::println( "   BBox: ({:.6f}, {:.6f}) -> ({:.6f}, {:.6f})", xmin, ymin, xmax, ymax );
        std::println( "   Noding Grid: {}x{} = {} tiles (Concurrent workers: {})",
                      grid_x, grid_y, grid_x * grid_y, num_workers );

        traffic::core::ThreadPool pool( num_workers );
        std::atomic<int> done{ 0 };

        // --- Sub-step 1/3: Task Distribution (Ordering by density) ---
        struct TileInfo { int gx, gy; int cnt; };
        std::vector<TileInfo> tasks;
        tasks.reserve( grid_x * grid_y );

        {
            std::println( "-> Sub-step 1/3: Analyzing density for optimal distribution..." );
            pqxx::connection c( conn_str_ );
            pqxx::nontransaction ntr( c );
            
            // Фильтруем NULL геометрии и используем подзапрос для корректной фильтрации gx/gy
            auto res = ntr.exec( std::vformat( R"(
                SELECT gx, gy, cnt FROM (
                    SELECT 
                        floor((ST_X(ST_Centroid(geom)) - {0}) / NULLIF({1}, 0))::int as gx,
                        floor((ST_Y(ST_Centroid(geom)) - {2}) / NULLIF({3}, 0))::int as gy,
                        count(*)::int as cnt
                    FROM graphs.edge_candidates
                    WHERE is_ground = TRUE AND geom IS NOT NULL
                    GROUP BY 1, 2
                ) t
                WHERE gx IS NOT NULL AND gy IS NOT NULL
            )", std::make_format_args( xmin, dx, ymin, dy ) ) );

            for( auto row : res )
                tasks.push_back( { row[ 0 ].as<int>(), row[ 1 ].as<int>(), row[ 2 ].as<int>() } );

            if( tasks.empty() )
            {
                std::println( "-> Sub-step 1/3: No active ground tiles found. Proceeding with default grid..." );
                for( int gy = 0; gy < grid_y; ++gy )
                    for( int gx = 0; gx < grid_x; ++gx )
                        tasks.push_back({ gx, gy, 0 });
            }
            else
            {
                // Сортировка по убыванию плотности
                std::sort( tasks.begin(), tasks.end(), []( const auto & a, const auto & b ) {
                    return a.cnt > b.cnt;
                } );
            }
        }

        int total = static_cast<int>( tasks.size() );
        std::println( "-> Sub-step 2/3: Processing {} active tiles (multithreaded)...", total );

        for( const auto & tile : tasks )
        {
            double tile_xmin = xmin + tile.gx * dx;
            double tile_ymin = ymin + tile.gy * dy;
            double tile_xmax = tile_xmin + dx;
            double tile_ymax = tile_ymin + dy;

            std::string sql = std::vformat( 
                GRID_NODING_TILE_SQL,
                std::make_format_args( tile_xmin, tile_ymin, tile_xmax, tile_ymax ) 
            );

            pool.Enqueue( [sql, &done, total, this]()
            {
                try
                {
                    pqxx::connection c( conn_str_ );
                    pqxx::work       w( c );
                    w.exec( sql );
                    w.commit();

                    int n = ++done;
                    DrawProgressBar( n * 100 / total, "Noding Grid Tiles" );
                }
                catch( const std::exception & e )
                {
                    std::println( stderr, "\n[ERROR] Thread failed in GridNoding: {}", e.what() );
                }
            } );
        }

        pool.WaitForAll();
        DrawProgressBar( 100, "Noding Grid Tiles Complete!" );
        std::println( "" );

        std::println( "-> Sub-step 2/3: Merging results and copying bridges..." );
        ExecuteQuery( "Copy Bridges", std::string( COPY_BRIDGES_SQL ) );

        std::println( "-> Sub-step 3/3: Building GiST/B-Tree Indexes & Analyzing (this may take a while)..." );
        ExecuteQuery( "Index Merged", std::string( INDEX_MERGED_SQL ) );
        
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "GridNoding failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::CreateTopology()
{
    try
    {
        std::println( "-> Step 3: Extract Topology (Hash-Join Strategy)" );
        
        std::println( "   [3.1/5] Initializing vertex tables..." );
        ExecuteQuery( "Topo Init", std::string( TOPOLOGY_INIT_SQL ) );

        std::println( "   [3.2/5] Extracting unique vertices..." );
        ExecuteQuery( "Topo Insert", std::string( TOPOLOGY_INSERT_VERTICES_SQL ) );

        std::println( "   [3.3/5] Indexing vertices & Preparing edges... (Spatial Index)" );
        ExecuteQuery( "Topo Index", std::string( TOPOLOGY_INDEX_VERTICES_SQL ) );

        std::println( "   [3.4/5] Mapping Source nodes to edges... (spatial join)" );
        ExecuteQuery( "Topo Sources", std::string( TOPOLOGY_UPDATE_SOURCES_SQL ) );

        std::println( "   [3.5/5] Mapping Target nodes to edges... (spatial join)" );
        ExecuteQuery( "Topo Targets", std::string( TOPOLOGY_UPDATE_TARGETS_SQL ) );

        ExecuteQuery( "Topo Analyze", std::string( TOPOLOGY_ANALYZE_SQL ) );
        
        std::println( "   Building nodes table..." );
        ExecuteQuery( "Fill Nodes", std::string( FILL_NODES_SQL ) );
        
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "CreateTopology failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::PopulateAttributes()
{
    try
    {
        std::println( "-> Step 4: Map Attributes & Finalize Schema" );
        ExecuteQuery( "Fill Edges", std::string( FILL_EDGES_SQL ) );
        ExecuteQuery( "Cleanup",    std::string( CLEANUP_SQL ) );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "PopulateAttributes failed: {}", e.what() ) );
    }
}

void SqlOrchestrator::LogLccDistribution()
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        auto res = work.exec( LOG_LCC_DISTRIBUTION_SQL );

        int64_t total_nodes = 0;
        for( auto row : res )
            total_nodes += row[ 1 ].as<int64_t>();

        std::println( "\n=== TOP-5 CONNECTED COMPONENTS (before LCC isolation) ===" );
        std::println( "{:<12} {:>12} {:>10}", "Component", "Nodes", "% of total" );
        std::println( "{:-<36}", "" );
        for( size_t i = 0; i < res.size(); ++i )
        {
            auto row = res[ i ];
            std::println( "{:<12} {:>12} {:>9.2f}%",
                          row[ 0 ].as<int64_t>(),
                          row[ 1 ].as<int64_t>(),
                          row[ 2 ].as<double>() );

            if( i == 0 && row[ 2 ].as<double>() < 95.0 )
            {
                std::println( stderr,
                    "\n[WARNING] Largest component < 95%! Grid Noding may have topology gaps."
                    " Check ST_SnapToGrid precision or tile boundary overlap." );
            }
        }
        std::println( "=========================================================" );
    }
    catch( const std::exception & e )
    {
        std::println( stderr, "LogLccDistribution failed: {}", e.what() );
    }
}

std::expected<void, std::string> SqlOrchestrator::IsolateLCC()
{
    try
    {
        std::println( "\n-> Step 5: Isolating LCC (Tarjan's connected components via pgr)" );
        LogLccDistribution();

        pqxx::connection conn( conn_str_ );
        pqxx::work       work( conn );

        std::println( "-> Deleting isolated nodes (CASCADE deletes orphaned edges)..." );
        work.exec( ISOLATE_LCC_SQL );
        work.commit();

        DrawProgressBar( 100, "Isolated Largest Connected Component!" );
        std::println( "" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "IsolateLCC failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::BuildEdgeBasedGraph()
{
    try
    {
        std::println( "\n-> Step 6: Building Edge-Based Graph (Line Graph transformation)" );
        std::println( "   Directed segments from graphs.edges (FWD + BWD)..." );

        ExecuteQuery( "Init EB Graph",   std::string( INIT_EB_GRAPH_SQL ) );
        ExecuteQuery( "Fill EB Nodes",   std::string( FILL_EB_NODES_SQL ) );

        int64_t eb_nodes = GetTableCount( "graphs.eb_nodes" );
        std::println( "   EB-Nodes created: {} directed segments", eb_nodes );

        std::println( "   Generating maneuvers with Turn Restrictions..." );
        
        // Check if osm.relations exists to avoid parse errors
        pqxx::connection check_conn( conn_str_ );
        pqxx::nontransaction ntr( check_conn );
        auto check_res = ntr.exec( "SELECT to_regclass('osm.turn_restrictions') IS NOT NULL" );
        bool has_relations = check_res[0][0].as<bool>();
        
        if (has_relations)
        {
            ExecuteQuery( "Fill EB Edges", std::string( FILL_EB_EDGES_SQL ) );
        }
        else
        {
            std::println( "   [INFO] osm.turn_restrictions NOT FOUND. Building EB-Edges WITHOUT Turn Restrictions." );
            ExecuteQuery( "Fill EB Edges (No TR)", std::string( FILL_EB_EDGES_NO_TR_SQL ) );
        }

        int64_t eb_edges = GetTableCount( "graphs.eb_edges" );
        std::println( "   EB-Edges created: {} legal maneuvers", eb_edges );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "BuildEdgeBasedGraph failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> SqlOrchestrator::PrintGraphStats( bool include_eb )
{
    try
    {
        pqxx::connection     conn( conn_str_ );
        pqxx::nontransaction work( conn );

        auto res = work.exec(
            "SELECT "
            "  (SELECT COUNT(*) FROM graphs.nodes) AS nodes, "
            "  (SELECT COUNT(*) FROM graphs.edges) AS edges, "
            "  (SELECT COALESCE(SUM(length_m)/1000, 0) FROM graphs.edges) AS km" );

        std::println( "\n=== GRAPH STATISTICS (Node-based, after LCC) ===" );
        std::println( "Nodes:            {}", res[ 0 ][ 0 ].as<int64_t>() );
        std::println( "Edges:            {}", res[ 0 ][ 1 ].as<int64_t>() );
        std::println( "Total Road Length: {:.2f} km", res[ 0 ][ 2 ].as<double>() );
        std::println( "================================================" );

        if( include_eb )
        {
            auto nb = work.exec( "SELECT COUNT(*) FROM graphs.eb_nodes" );
            auto me = work.exec( "SELECT COUNT(*) FROM graphs.eb_edges" );
            std::println( "\n=== EDGE-BASED GRAPH STATISTICS ===" );
            std::println( "EB-Nodes (directed segments): {}", nb[ 0 ][ 0 ].as<int64_t>() );
            std::println( "EB-Edges (legal maneuvers):   {}", me[ 0 ][ 0 ].as<int64_t>() );
            std::println( "=====================================" );
        }

        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "PrintGraphStats failed: {}", e.what() ) );
    }
}

} // namespace traffic::graph_builder
