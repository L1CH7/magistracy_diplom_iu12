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

    void SetFlags( bool skip_db, bool skip_eb, bool skip_landmarks, bool skip_attr, bool overwrite );

    // Returns an error string if pipeline fails
    std::expected<void, std::string> RunPipeline();

private:
    bool IsStageComplete( const std::string & stage );
    void RecordStageComplete( const std::string & stage );

private:
    std::string conn_str_;
    bool skip_db_        = false;
    bool skip_eb_        = false;
    bool skip_landmarks_ = false;
    bool skip_attr_      = false;
    bool overwrite_      = false;
};

} // namespace traffic::graph_builder
