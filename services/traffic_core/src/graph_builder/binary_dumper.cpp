#include "binary_dumper.hpp"
#include <pqxx/pqxx>
#include <print>
#include <format>
#include <fstream>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <stdexcept>
#include <cstdint>

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
}

BinaryDumper::BinaryDumper( std::string connection_string )
:   conn_str_( std::move( connection_string ) )
{}

BinaryDumper::~BinaryDumper() = default;

std::expected<void, std::string> BinaryDumper::CalculateLandmarks()
{
    std::println( "-> (CalculateLandmarks) Placeholder: requires in-memory EB CSR." );
    return {};
}

std::expected<void, std::string> BinaryDumper::DumpCSR()
{
    try
    {
        pqxx::connection     conn( conn_str_ );
        pqxx::nontransaction work( conn );

        DrawProgressBar( 0, "Reading EB-nodes (directed segments)..." );
        auto nodes_res = work.exec( "SELECT id FROM graphs.eb_nodes ORDER BY id" );

        std::unordered_map<int64_t, uint32_t> node_map;
        node_map.reserve( nodes_res.size() );
        uint32_t dense_id = 0;
        for( auto row : nodes_res )
            node_map[ row[ 0 ].as<int64_t>() ] = dense_id++;

        uint32_t num_nodes = dense_id;

        DrawProgressBar( 25, "Reading EB-edges (maneuvers)..." );
        auto edges_res = work.exec(
            "SELECT ee.from_eb_node, ee.to_eb_node, "
            "       ROUND(en_to.length_m)::INT, "
            "       ROUND(en_to.t_free + ee.maneuver_time)::INT "
            "FROM graphs.eb_edges ee "
            "JOIN graphs.eb_nodes en_to ON en_to.id = ee.to_eb_node "
            "ORDER BY ee.from_eb_node" );

        struct Edge
        {
            uint32_t src, tgt, length_m, base_time_sec;
        };
        std::vector<Edge> edges;
        edges.reserve( edges_res.size() );

        for( auto row : edges_res )
        {
            auto src_it = node_map.find( row[ 0 ].as<int64_t>() );
            auto tgt_it = node_map.find( row[ 1 ].as<int64_t>() );
            if( src_it == node_map.end() || tgt_it == node_map.end() ) continue;

            edges.push_back( {
                src_it->second, tgt_it->second,
                static_cast<uint32_t>( std::max( row[ 2 ].as<int64_t>(), 0L ) ),
                static_cast<uint32_t>( std::max( row[ 3 ].as<int64_t>(), 1L ) )
            } );
        }
        uint32_t num_edges = static_cast<uint32_t>( edges.size() );

        DrawProgressBar( 50, "Generating FWD CSR layout..." );
        std::vector<uint32_t> fwd_row_ptr( num_nodes + 1, 0 );
        std::vector<uint32_t> fwd_col_ind( num_edges );
        std::vector<uint32_t> fwd_length( num_edges );
        std::vector<uint32_t> fwd_base_time( num_edges );

        for( const auto & e : edges )
            fwd_row_ptr[ e.src + 1 ]++;
        for( uint32_t i = 0; i < num_nodes; ++i )
            fwd_row_ptr[ i + 1 ] += fwd_row_ptr[ i ];

        {
            std::vector<uint32_t> cur( fwd_row_ptr.begin(), fwd_row_ptr.end() );
            for( const auto & e : edges )
            {
                uint32_t pos = cur[ e.src ]++;
                fwd_col_ind[ pos ]  = e.tgt;
                fwd_length[ pos ]   = e.length_m;
                fwd_base_time[ pos ] = e.base_time_sec;
            }
        }

        DrawProgressBar( 75, "Writing csr.bin..." );
        {
            std::ofstream out( "/app/data/csr.bin", std::ios::binary );
            if( !out )
                return std::unexpected( "Cannot write /app/data/csr.bin" );
            size_t n = num_nodes, m = num_edges;
            out.write( reinterpret_cast<const char *>( &n ), sizeof( n ) );
            out.write( reinterpret_cast<const char *>( &m ), sizeof( m ) );
            out.write( reinterpret_cast<const char *>( fwd_row_ptr.data() ),
                       fwd_row_ptr.size() * sizeof( uint32_t ) );
            out.write( reinterpret_cast<const char *>( fwd_col_ind.data() ),
                       fwd_col_ind.size() * sizeof( uint32_t ) );
            out.write( reinterpret_cast<const char *>( fwd_length.data() ),
                       fwd_length.size() * sizeof( uint32_t ) );
            out.write( reinterpret_cast<const char *>( fwd_base_time.data() ),
                       fwd_base_time.size() * sizeof( uint32_t ) );
        }

        DrawProgressBar( 85, "Writing csr_rev.bin..." );
        std::sort( edges.begin(), edges.end(), []( const Edge & a, const Edge & b )
        {
            return a.tgt < b.tgt;
        } );

        std::vector<uint32_t> rev_row_ptr( num_nodes + 1, 0 );
        std::vector<uint32_t> rev_col_ind( num_edges );
        std::vector<uint32_t> rev_base_time( num_edges );

        for( const auto & e : edges )
            rev_row_ptr[ e.tgt + 1 ]++;
        for( uint32_t i = 0; i < num_nodes; ++i )
            rev_row_ptr[ i + 1 ] += rev_row_ptr[ i ];

        {
            std::vector<uint32_t> cur( rev_row_ptr.begin(), rev_row_ptr.end() );
            for( const auto & e : edges )
            {
                uint32_t pos = cur[ e.tgt ]++;
                rev_col_ind[ pos ]    = e.src;
                rev_base_time[ pos ]  = e.base_time_sec;
            }
        }

        {
            std::ofstream rout( "/app/data/csr_rev.bin", std::ios::binary );
            if( !rout )
                return std::unexpected( "Cannot write /app/data/csr_rev.bin" );
            size_t n = num_nodes, m = num_edges;
            rout.write( reinterpret_cast<const char *>( &n ), sizeof( n ) );
            rout.write( reinterpret_cast<const char *>( &m ), sizeof( m ) );
            rout.write( reinterpret_cast<const char *>( rev_row_ptr.data() ),
                        rev_row_ptr.size() * sizeof( uint32_t ) );
            rout.write( reinterpret_cast<const char *>( rev_col_ind.data() ),
                        rev_col_ind.size() * sizeof( uint32_t ) );
            rout.write( reinterpret_cast<const char *>( rev_base_time.data() ),
                        rev_base_time.size() * sizeof( uint32_t ) );
        }

        DrawProgressBar( 100, "CSR dumps written (csr.bin, csr_rev.bin)" );
        std::println( "" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "DumpCSR failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> BinaryDumper::DumpAttributes()
{
    try
    {
        pqxx::connection     conn( conn_str_ );
        pqxx::nontransaction work( conn );

        auto res = work.exec(
            "SELECT speed_kmh, lanes, highway, oneway "
            "FROM graphs.eb_nodes "
            "ORDER BY id" );

        uint32_t num_entries = static_cast<uint32_t>( res.size() );
        DrawProgressBar( 0, "Writing attributes.bin..." );

        std::ofstream out( "/app/data/attributes.bin", std::ios::binary );
        if( !out )
            return std::unexpected( "Cannot write /app/data/attributes.bin" );

        out.write( reinterpret_cast<const char *>( &num_entries ), sizeof( num_entries ) );

        for( auto row : res )
        {
            float   speed  = static_cast<float>( row[ 0 ].as<double>() );
            uint8_t lanes  = static_cast<uint8_t>( std::min( row[ 1 ].as<int>(), 8 ) );

            uint8_t hw = 3;
            if( !row[ 2 ].is_null() )
            {
                std::string h = row[ 2 ].as<std::string>();
                if( h == "motorway" || h == "motorway_link" ||
                    h == "trunk"    || h == "trunk_link" )
                    hw = 0;
                else if( h == "primary"   || h == "primary_link"   ||
                         h == "secondary" || h == "secondary_link" )
                    hw = 1;
                else if( h == "tertiary"  || h == "tertiary_link" )
                    hw = 2;
            }

            uint8_t oneway = row[ 3 ].is_null() ? 0
                           : static_cast<uint8_t>( row[ 3 ].as<int>() != 0 ? 1 : 0 );
            uint8_t pad = 0;

            out.write( reinterpret_cast<const char *>( &speed ),  sizeof( speed ) );
            out.write( reinterpret_cast<const char *>( &lanes ),  sizeof( lanes ) );
            out.write( reinterpret_cast<const char *>( &hw ),     sizeof( hw ) );
            out.write( reinterpret_cast<const char *>( &oneway ), sizeof( oneway ) );
            out.write( reinterpret_cast<const char *>( &pad ),    sizeof( pad ) );
        }

        DrawProgressBar( 100, "attributes.bin ready!" );
        std::println( "" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "DumpAttributes failed: {}", e.what() ) );
    }
}

std::expected<void, std::string> BinaryDumper::DumpRTree()
{
    try
    {
        pqxx::connection     conn( conn_str_ );
        pqxx::nontransaction work( conn );

        auto res = work.exec(
            "SELECT "
            "  ST_XMin(geom), ST_YMin(geom), "
            "  ST_XMax(geom), ST_YMax(geom) "
            "FROM graphs.eb_nodes "
            "ORDER BY id" );

        uint32_t num_entries = static_cast<uint32_t>( res.size() );
        DrawProgressBar( 0, "Writing r-tree.bin (flat BBox per EB-node)..." );

        std::ofstream out( "/app/data/r-tree.bin", std::ios::binary );
        if( !out )
            return std::unexpected( "Cannot write /app/data/r-tree.bin" );

        out.write( reinterpret_cast<const char *>( &num_entries ), sizeof( num_entries ) );

        for( uint32_t i = 0; i < num_entries; ++i )
        {
            auto row  = res[ i ];
            float xmin = static_cast<float>( row[ 0 ].as<double>() );
            float ymin = static_cast<float>( row[ 1 ].as<double>() );
            float xmax = static_cast<float>( row[ 2 ].as<double>() );
            float ymax = static_cast<float>( row[ 3 ].as<double>() );

            out.write( reinterpret_cast<const char *>( &xmin ), sizeof( xmin ) );
            out.write( reinterpret_cast<const char *>( &ymin ), sizeof( ymin ) );
            out.write( reinterpret_cast<const char *>( &xmax ), sizeof( xmax ) );
            out.write( reinterpret_cast<const char *>( &ymax ), sizeof( ymax ) );
            out.write( reinterpret_cast<const char *>( &i ),    sizeof( i ) );
        }

        DrawProgressBar( 100, "r-tree.bin ready!" );
        std::println( "" );
        return {};
    }
    catch( const std::exception & e )
    {
        return std::unexpected( std::format( "DumpRTree failed: {}", e.what() ) );
    }
}

} // namespace traffic::graph_builder
