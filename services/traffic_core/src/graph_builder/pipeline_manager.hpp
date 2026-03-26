#pragma once

#include <string>
#include <expected>

namespace traffic::graph_builder
{

class PipelineManager
{
public:
    explicit PipelineManager( std::string connection_string );
    ~PipelineManager();

    void SetFlags( bool csr_only, bool recursive, bool overwrite );

    // Returns an error string if pipeline fails
    std::expected<void, std::string> RunPipeline();

private:
    bool IsStageComplete( const std::string & stage );
    void RecordStageComplete( const std::string & stage );

private:
    std::string conn_str_;
    bool csr_only_  = false;
    bool recursive_ = false;
    bool overwrite_ = false;
};

} // namespace traffic::graph_builder
