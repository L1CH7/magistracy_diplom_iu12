#pragma once

#include <string>
#include <string_view>
#include <expected>

namespace traffic::graph_builder
{

class SqlOrchestrator
{
public:
    explicit SqlOrchestrator( std::string connection_string );
    ~SqlOrchestrator();

    std::expected<void, std::string> InitializeSchema();
    std::expected<void, std::string> ExtractCandidates();
    std::expected<void, std::string> GridNoding();
    std::expected<void, std::string> CreateTopology();
    std::expected<void, std::string> PopulateAttributes();
    std::expected<void, std::string> IsolateLCC();
    std::expected<void, std::string> BuildEdgeBasedGraph();
    std::expected<void, std::string> IsolateEbLCC();
    
    std::expected<void, std::string> PrintGraphStats( bool include_eb );

private:
    void ExecuteQuery( std::string_view query_name, std::string_view sql );
    int64_t GetTableCount( std::string_view table_name );
    void LogLccDistribution();
    void LogEbLccDistribution();

private:
    std::string conn_str_;
};

} // namespace traffic::graph_builder
