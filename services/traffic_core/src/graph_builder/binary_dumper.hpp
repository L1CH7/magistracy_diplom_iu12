#pragma once

#include <string>
#include <expected>

namespace traffic::graph_builder
{

class BinaryDumper
{
public:
    explicit BinaryDumper( std::string connection_string );
    ~BinaryDumper();

    std::expected<void, std::string> DumpCSR();
    std::expected<void, std::string> DumpAttributes();
    std::expected<void, std::string> DumpRTree();

private:
    std::string conn_str_;
};

} // namespace traffic::graph_builder
