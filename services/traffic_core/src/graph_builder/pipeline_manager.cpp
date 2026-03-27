#include "pipeline_manager.hpp"
#include "sql_orchestrator.hpp"
#include "binary_dumper.hpp"
#include "landmarks.hpp"

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

void PipelineManager::SetFlags( bool skip_db, bool skip_eb, bool skip_landmarks, bool skip_attr, bool overwrite )
{
    skip_db_        = skip_db;
    skip_eb_        = skip_eb;
    skip_landmarks_ = skip_landmarks;
    skip_attr_      = skip_attr;
    overwrite_      = overwrite;
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

    SqlOrchestrator sql( conn_str_ );
    BinaryDumper    dumper( conn_str_ );

    // --- DB PIPELINE PHASE ---
    if( !skip_db_ )
    {
        // 1. Schema Init
        if( overwrite_ || !IsStageComplete( "schema_initialized" ) )
        {
            auto res = sql.InitializeSchema();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "schema_initialized" );
        }

        // 2-6 (Noding to LCC)
        if( overwrite_ || !IsStageComplete( "lcc_isolated" ) )
        {
            if( overwrite_ || !IsStageComplete( "candidates_extracted" ) )
            {
                if( auto r = sql.ExtractCandidates(); !r ) return std::unexpected( r.error() );
                RecordStageComplete( "candidates_extracted" );
            }

            if( overwrite_ || !IsStageComplete( "grid_noded" ) )
            {
                if( auto r = sql.GridNoding(); !r ) return std::unexpected( r.error() );
                RecordStageComplete( "grid_noded" );
            }

            if( overwrite_ || !IsStageComplete( "topology_created" ) )
            {
                if( auto r = sql.CreateTopology(); !r ) return std::unexpected( r.error() );
                RecordStageComplete( "topology_created" );
            }

            if( overwrite_ || !IsStageComplete( "attributes_populated" ) )
            {
                if( auto r = sql.PopulateAttributes(); !r ) return std::unexpected( r.error() );
                RecordStageComplete( "attributes_populated" );
            }

            if( overwrite_ || !IsStageComplete( "lcc_isolated" ) )
            {
                if( auto r = sql.IsolateLCC(); !r ) return std::unexpected( r.error() );
                RecordStageComplete( "lcc_isolated" );
            }
        }

        if( auto r = sql.PrintGraphStats( false ); !r ) return std::unexpected( r.error() );

        // 7. Edge-Based Graph
        if( !skip_eb_ && ( overwrite_ || !IsStageComplete( "edge_based_graph" ) ) )
        {
            auto res = sql.BuildEdgeBasedGraph();
            if( !res ) return std::unexpected( res.error() );
            RecordStageComplete( "edge_based_graph" );
        }
        
        if( IsStageComplete( "edge_based_graph" ) )
        {
            if( auto r = sql.PrintGraphStats( true ); !r ) return std::unexpected( r.error() );
        }
    }
    else
    {
        std::println( "\n-> Skipping DB pipeline stages (--skip-db)." );
    }

    // --- BINARY ARTIFACTS PHASE ---
    if( IsStageComplete( "edge_based_graph" ) )
    {
        // ВАЖНО: Все дампы зависят от единой RAM-топологии (Z-order)
        std::println( "\n-> Loading graph into RAM (Z-curve reordering)..." );
        if( auto r = dumper.LoadAndSortNodes(); !r ) return std::unexpected( r.error() );

        // 8. CSR Dump
        std::println( "\n-> Step 7: Dumping CSR (csr.bin, csr_rev.bin)" );
        if( auto r = dumper.DumpCSR(); !r ) return std::unexpected( r.error() );

        // 9. ALT Landmarks
        if( !skip_landmarks_ )
        {
            std::println( "\n-> Step 8: ALT Landmarks (Minmax + MaxCover)" );
            traffic::graph_builder::LandmarkBuilder lm_builder;
            if( auto r = lm_builder.Build( "/app/data/csr.bin", "/app/data/csr_rev.bin", "/app/data/landmarks.bin" ); !r )
                return std::unexpected( r.error() );
        }

        // 10. Extended Attributes
        if( !skip_attr_ )
        {
            std::println( "\n-> Step 9: Dumping Attributes & Geometry (SoA)" );
            if( auto r = dumper.DumpExtendedAttributes(); !r ) return std::unexpected( r.error() );
            
            std::println( "\n-> Step 10: Dumping BBox Index (r-tree.bin)" );
            if( auto r = dumper.DumpRTree(); !r ) return std::unexpected( r.error() );
        }
    }
    else
    {
        std::println( "\n[WARNING] Edge-based graph not ready. Skipping binary dumps." );
    }

    std::println( "\n=== PIPELINE FINISHED SUCCESSFULLY ===" );
    return {};
}

} // namespace traffic::graph_builder
