#pragma once

#include <string>
#include <string_view>

namespace traffic::graph_builder
{

class DbOrchestrator
{
public:
    explicit DbOrchestrator( std::string connection_string );
    ~DbOrchestrator();
    
    // Выполняет полный конвейер: извлечение, нодирование, топология, атрибуты.
    void RunPipeline();

    void SetFlags(bool csr_only, bool recursive, bool overwrite);

private:
    void ExecuteQuery( std::string_view query_name, std::string_view sql );
    int64_t GetTableCount( std::string_view table_name );
    void DrawProgressBar( int percent, std::string_view message );

    void ExtractCandidates();
    void GridNoding();
    void CreateTopology();
    void PopulateAttributes();
    void IsolateLCC();
    void PrintGraphStats();

    void CalculateLandmarks();
    void DumpCSR();           // -> csr.bin, csr_rev.bin
    void DumpAttributes();    // -> attributes.bin
    void DumpRTree();         // -> r-tree.bin

    bool IsStageComplete(const std::string& stage);
    void RecordStageComplete(const std::string& stage);

private:
    std::string conn_str_;
    bool csr_only_ = false;
    bool recursive_ = false;
    bool overwrite_ = false;
};

} // namespace traffic::graph_builder
