# Two-Stage Configuration (Compile-Time Parameters)
# These constants are evaluated at compile time for loop unrolling and structural alignment.
# Reference: plans/NAV MAS Plan sem2 1.0.md & .agents/rules/04_cmake_and_config.md

set(TRAFFIC_NUM_BUCKETS 24 CACHE STRING "Number of 5-minute time buckets")
set(TRAFFIC_SLOT_SEC 300 CACHE STRING "Length of one bucket in seconds")
set(TRAFFIC_TOTAL_LANDMARKS 16 CACHE STRING "Total number of ALT landmarks in the graph")
set(TRAFFIC_ACTIVE_LANDMARKS 4 CACHE STRING "Number of active ALT landmarks per query")
set(TRAFFIC_CACHE_LINE_SIZE 64 CACHE STRING "CPU Cache Line Size in bytes for alignments")
set(TRAFFIC_MPR_TOLERANCE_NUM 3 CACHE STRING "MPR ETA Tolerance Numerator (e.g., 3 for 1.5x)")
set(TRAFFIC_MPR_TOLERANCE_DEN 2 CACHE STRING "MPR ETA Tolerance Denominator (e.g., 2 for 1.5x)")
set(TRAFFIC_MAX_ROUTE_PATH 128 CACHE STRING "Max number of edges in a RouteResponse POD")
set(QUILL_COMPILE_ACTIVE_LOG_LEVEL "QUILL_LOG_LEVEL_INFO" CACHE STRING "Active log level for Quill in compile-time")

# Hardware Topology Configuration
set(TRAFFIC_ROUTER_THREADS "6" CACHE STRING "Number of threads for router pool")
set(TRAFFIC_ROUTER_CORES "2,8,3,9,4,10,5,11" CACHE STRING "Explicit logical CPUs for router pool (10 threads on cores 2-6)")
set(TRAFFIC_SIM_AFFINITY "1" CACHE STRING "Core 1 (Thread 1) for Main Simulator + MPR")
set(TRAFFIC_DISPATCH_AFFINITY "7" CACHE STRING "Core 1 (Thread 9) for Router Dispatcher")
set(TRAFFIC_AVOID_OS_CORES "1" CACHE STRING "Reserved Core 0 (Threads 0, 8) for OS")

# Add definitions to be visible in C++
add_compile_definitions(
    TRAFFIC_NUM_BUCKETS=${TRAFFIC_NUM_BUCKETS}
    TRAFFIC_SLOT_SEC=${TRAFFIC_SLOT_SEC}
    TRAFFIC_TOTAL_LANDMARKS=${TRAFFIC_TOTAL_LANDMARKS}
    TRAFFIC_ACTIVE_LANDMARKS=${TRAFFIC_ACTIVE_LANDMARKS}
    TRAFFIC_CACHE_LINE_SIZE=${TRAFFIC_CACHE_LINE_SIZE}
    TRAFFIC_MPR_TOLERANCE_NUM=${TRAFFIC_MPR_TOLERANCE_NUM}
    TRAFFIC_MPR_TOLERANCE_DEN=${TRAFFIC_MPR_TOLERANCE_DEN}
    TRAFFIC_MAX_ROUTE_PATH=${TRAFFIC_MAX_ROUTE_PATH}
    TRAFFIC_ROUTER_THREADS=${TRAFFIC_ROUTER_THREADS}
    TRAFFIC_ROUTER_CORES="${TRAFFIC_ROUTER_CORES}"
    TRAFFIC_SIM_AFFINITY=${TRAFFIC_SIM_AFFINITY}
    TRAFFIC_DISPATCH_AFFINITY=${TRAFFIC_DISPATCH_AFFINITY}
    TRAFFIC_AVOID_OS_CORES=${TRAFFIC_AVOID_OS_CORES}
)
