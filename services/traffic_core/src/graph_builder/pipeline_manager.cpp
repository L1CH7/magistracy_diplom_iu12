#include "pipeline_manager.hpp"
#include "sql_orchestrator.hpp"
#include "binary_dumper.hpp"

#include <pqxx/pqxx>
#include <print>
#include <format>
#include <stdexcept>

namespace traffic::graph_builder
{

PipelineManager::PipelineManager( std::string connection_string )
:   conn_str_( std::move( connection_string ) )
{}

PipelineManager::~PipelineManager() = default;

void PipelineManager::SetFlags( bool dump_only, bool skip_noding, bool recursive, bool overwrite )
{
    dump_only_  = dump_only;
    skip_noding_ = skip_noding;
    recursive_  = recursive;
    overwrite_  = overwrite;
}

bool PipelineManager::IsStageComplete( const std::string & stage )
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::nontransaction work( conn );
        pqxx::params p;
        p.append( stage );
        auto res = work.exec(
            "SELECT 1 FROM graphs.builder_state WHERE stage = $1", p );
        return !res.empty();
    }
    catch( ... )
    {
        return false;
    }
}

void PipelineManager::RecordStageComplete( const std::string & stage )
{
    try
    {
        pqxx::connection conn( conn_str_ );
        pqxx::work       work( conn );
        pqxx::params p;
        p.append( stage );
        work.exec(
            "INSERT INTO graphs.builder_state (stage) VALUES ($1) "
            "ON CONFLICT (stage) DO NOTHING", p );
        work.commit();
    }
    catch( ... ) {}
}

std::expected<void, std::string> PipelineManager::RunPipeline()
{
    std::println( "\n=== TRAFFIC GRAPH BUILDER | PIPELINE START ===" );

    bool need_db_build = true;
    if( dump_only_ && !recursive_ && !overwrite_ )
    {
        need_db_build = false;
        if( !IsStageComplete( "edge_based_graph" ) )
            return std::unexpected( "Edge-based graph missing! Use --recursive to build it." );
    }

    SqlOrchestrator sql( conn_str_ );
    BinaryDumper    dumper( conn_str_ );

    if( need_db_build )
    {
        // 1. Schema Init
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "schema_initialized" ) ) )
        {
            auto res = sql.InitializeSchema();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "schema_initialized" );
        }

        // 2. Extract Candidates
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "candidates_extracted" ) ) )
        {
            auto res = sql.ExtractCandidates();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "candidates_extracted" );
        }

        // 3. Grid Noding
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "grid_noding" ) ) )
        {
            auto res = sql.GridNoding();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "grid_noding" );
        }

        // 4. Create Topology
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "topology_extracted" ) ) )
        {
            auto res = sql.CreateTopology();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "topology_extracted" );
        }

        // 5. Populate Attributes
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "attributes_mapped" ) ) )
        {
            auto res = sql.PopulateAttributes();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "attributes_mapped" );
        }

        // 6. Isolate LCC
        if( !skip_noding_ && ( overwrite_ || !IsStageComplete( "lcc_isolated" ) ) )
        {
            auto res = sql.IsolateLCC();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "lcc_isolated" );
        }

        // Stats after Node-based LCC
        if( auto r = sql.PrintGraphStats( false ); !r ) return std::unexpected( r.error() );

        // 7. Build Edge-based Graph
        if( overwrite_ || !IsStageComplete( "edge_based_graph" ) )
        {
            auto res = sql.BuildEdgeBasedGraph();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "edge_based_graph" );
        }

        // Stats after Edge-based Transform
        if( auto r = sql.PrintGraphStats( true ); !r ) return std::unexpected( r.error() );
    }
    else
    {
        std::println( "\n-> DB graph ready. Skipping DB pipeline (--dump-only mode)." );
    }

    // Binary Dumps Phase
    if( IsStageComplete( "edge_based_graph" ) )
    {
        // 8. ALT Landmarks (placeholder)
        std::println( "\n-> Step 7: ALT Landmarks" );
        if( auto r = dumper.CalculateLandmarks(); !r ) return std::unexpected( r.error() );

        // 9. CSR Dump
        std::println( "\n-> Step 8: Dumping CSR (csr.bin, csr_rev.bin)" );
        if( auto r = dumper.DumpCSR(); !r ) return std::unexpected( r.error() );

        // 10. Attributes Dump
        std::println( "\n-> Step 9: Dumping Edge Attributes (attributes.bin)" );
        if( auto r = dumper.DumpAttributes(); !r ) return std::unexpected( r.error() );

        // 11. R-Tree Dump
        std::println( "\n-> Step 10: Dumping Flat BBox Index (r-tree.bin)" );
        if( auto r = dumper.DumpRTree(); !r ) return std::unexpected( r.error() );
    }

    std::println( "\n=== PIPELINE FINISHED SUCCESSFULLY ===" );
    return {};
}

} // namespace traffic::graph_builder
