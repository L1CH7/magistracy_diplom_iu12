# Two-Stage Configuration (Compile-Time Parameters)
# These constants are evaluated at compile time for loop unrolling and structural alignment.
# Reference: plans/NAV MAS Plan sem2 1.0.md & .agents/rules/04_cmake_and_config.md

set(TRAFFIC_NUM_BUCKETS 24 CACHE STRING "Number of 5-minute time buckets")
set(TRAFFIC_SLOT_SEC 300 CACHE STRING "Length of one bucket in seconds")
set(TRAFFIC_TOTAL_LANDMARKS 16 CACHE STRING "Total number of ALT landmarks in the graph")
set(TRAFFIC_ACTIVE_LANDMARKS 4 CACHE STRING "Number of active ALT landmarks per query")
set(TRAFFIC_CACHE_LINE_SIZE 64 CACHE STRING "CPU Cache Line Size in bytes for alignments")
set(QUILL_COMPILE_ACTIVE_LOG_LEVEL "QUILL_LOG_LEVEL_INFO" CACHE STRING "Active log level for Quill in compile-time")

# Add definitions to be visible in C++
add_compile_definitions(
    TRAFFIC_NUM_BUCKETS=${TRAFFIC_NUM_BUCKETS}
    TRAFFIC_SLOT_SEC=${TRAFFIC_SLOT_SEC}
    TRAFFIC_TOTAL_LANDMARKS=${TRAFFIC_TOTAL_LANDMARKS}
    TRAFFIC_ACTIVE_LANDMARKS=${TRAFFIC_ACTIVE_LANDMARKS}
    TRAFFIC_CACHE_LINE_SIZE=${TRAFFIC_CACHE_LINE_SIZE}
)
