#include "pipeline_manager.hpp"
#include <cstdlib>
#include <print>
#include <format>
#include <string_view>

int main( int argc, char * argv[] )
{
    bool dump_only = false;
    bool skip_noding = false;
    bool recursive = false;
    bool overwrite = false;

    for( int i = 1; i < argc; ++i )
    {
        std::string_view arg = argv[ i ];
        if( arg == "--csr" || arg == "--dump-only" ) dump_only = true;
        if( arg == "--skip-noding" ) skip_noding = true;
        if( arg == "--recursive" ) recursive = true;
        if( arg == "--overwrite" ) overwrite = true;
    }

    std::println( "Traffic Graph Builder (Offline Pipeline)" );

    const char * db_host = std::getenv( "APP__DB__HOST" ) ? std::getenv( "APP__DB__HOST" ) : "localhost";
    const char * db_port = std::getenv( "APP__DB__PORT" ) ? std::getenv( "APP__DB__PORT" ) : "5432";
    const char * db_name = std::getenv( "APP__DB__NAME" ) ? std::getenv( "APP__DB__NAME" ) : "nav_mas";
    const char * db_user = std::getenv( "APP__DB__USER" ) ? std::getenv( "APP__DB__USER" ) : "postgres";
    const char * db_pass = std::getenv( "APP__DB__PASSWORD" ) ? std::getenv( "APP__DB__PASSWORD" ) : "postgres";

    std::string conn_str = std::format( "host={} port={} dbname={} user={} password={}",
                                        db_host, db_port, db_name, db_user, db_pass );

    traffic::graph_builder::PipelineManager pipeline( conn_str );
    pipeline.SetFlags( dump_only, skip_noding, recursive, overwrite );
    
    auto res = pipeline.RunPipeline();
    if( !res )
    {
        std::println( stderr, "Pipeline Error: {}", res.error() );
        return 1;
    }

    std::println( "Pipeline Finished." );
    return 0;
}
