#include "db_orchestrator.hpp"
#include <cstdlib>
#include <print>
#include <format>
#include <string_view>

int main( int argc, char * argv[] )
{
    bool csr_only = false;
    bool recursive = false;
    bool overwrite = false;

    for( int i = 1; i < argc; ++i )
    {
        std::string_view arg = argv[ i ];
        if( arg == "--csr" ) csr_only = true;
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

    traffic::graph_builder::DbOrchestrator db( conn_str );
    db.SetFlags( csr_only, recursive, overwrite );
    db.RunPipeline();

    std::println( "Pipeline Finished." );
    return 0;
}
