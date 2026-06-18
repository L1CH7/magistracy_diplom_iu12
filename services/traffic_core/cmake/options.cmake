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
set(TRAFFIC_ROUTER_MAX_QPS 4000 CACHE STRING "Max queries per second for the router pool")
set(TRAFFIC_BASE_FPS 25 CACHE STRING "Base ticks per second for quota calculations")
set(QUILL_COMPILE_ACTIVE_LOG_LEVEL "QUILL_LOG_LEVEL_INFO" CACHE STRING "Active log level for Quill in compile-time")

# === Feature / Performance Flags ===
set(TRAFFIC_DISABLE_ROUTER_BPR OFF CACHE STRING "Disable BPR congestion weights in the router for purely static routing (ON/OFF)")
set(TRAFFIC_ENABLE_ROUTER_PROFILE ON CACHE STRING "Enable CPU cycle profiling and search space counting in A* (ON/OFF)")

# Convert ON/OFF strings or booleans to 1/0 for C++ preprocessor
if(TRAFFIC_DISABLE_ROUTER_BPR STREQUAL "ON" OR TRAFFIC_DISABLE_ROUTER_BPR)
    set(DISABLE_BPR_VAL 1)
else()
    set(DISABLE_BPR_VAL 0)
endif()

if(TRAFFIC_ENABLE_ROUTER_PROFILE STREQUAL "ON" OR TRAFFIC_ENABLE_ROUTER_PROFILE)
    set(ROUTER_PROFILE_VAL 1)
else()
    set(ROUTER_PROFILE_VAL 0)
endif()

# === Capacity / BPR Physics Constants ===
# Физический размер одной машины (корпус + минимальный зазор) в метрах
set(TRAFFIC_CAR_LENGTH_M 7 CACHE STRING "Physical car slot length in meters (body + min gap)")
# Время реакции водителя (сек) для расчёта дистанции на высокой скорости (магистраль ≥ 90 км/ч)
set(TRAFFIC_SAFE_TIME_HIGHWAY_SEC 3 CACHE STRING "Safe following time on highway (speed >= 90 km/h), seconds")
# Время реакции для городских дорог (40–90 км/ч)
set(TRAFFIC_SAFE_TIME_URBAN_SEC 2 CACHE STRING "Safe following time in urban flow (40-90 km/h), seconds")
# Время реакции для плотной застройки / пробок (≤ 40 км/ч)
set(TRAFFIC_SAFE_TIME_DENSE_SEC 15 CACHE STRING "Safe following time in dense/jam flow (speed <= 40 km/h), seconds x10 (1.5s)")
# Порог скорости (км/ч) разделяющий магистраль и город
set(TRAFFIC_SPEED_HIGHWAY_KMH 90 CACHE STRING "Speed threshold for highway capacity calc, km/h")
# Порог скорости (км/ч) разделяющий городской и плотный поток
set(TRAFFIC_SPEED_DENSE_KMH 40 CACHE STRING "Speed threshold for dense/jam capacity calc, km/h")
# Дефолтное кол-во полос если поле lanes = NULL в OSM
set(TRAFFIC_DEFAULT_LANES 1 CACHE STRING "Default number of lanes when OSM lanes tag is missing")

# Hardware Topology Configuration (авто-вычисление — см. cmake/thread-affinity.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/thread-affinity.cmake)

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
    TRAFFIC_ROUTER_MAX_QPS=${TRAFFIC_ROUTER_MAX_QPS}
    TRAFFIC_BASE_FPS=${TRAFFIC_BASE_FPS}
    TRAFFIC_ROUTER_THREADS=${TRAFFIC_ROUTER_THREADS}
    TRAFFIC_ROUTER_CORES="${TRAFFIC_ROUTER_CORES}"
    TRAFFIC_SIM_AFFINITY=${TRAFFIC_SIM_AFFINITY}
    TRAFFIC_DISPATCH_AFFINITY=${TRAFFIC_DISPATCH_AFFINITY}
    TRAFFIC_AVOID_OS_CORES=${TRAFFIC_AVOID_OS_CORES}
    # Capacity / BPR Physics
    TRAFFIC_CAR_LENGTH_M=${TRAFFIC_CAR_LENGTH_M}
    TRAFFIC_SAFE_TIME_HIGHWAY_SEC=${TRAFFIC_SAFE_TIME_HIGHWAY_SEC}
    TRAFFIC_SAFE_TIME_URBAN_SEC=${TRAFFIC_SAFE_TIME_URBAN_SEC}
    TRAFFIC_SAFE_TIME_DENSE_SEC=${TRAFFIC_SAFE_TIME_DENSE_SEC}
    TRAFFIC_SPEED_HIGHWAY_KMH=${TRAFFIC_SPEED_HIGHWAY_KMH}
    TRAFFIC_SPEED_DENSE_KMH=${TRAFFIC_SPEED_DENSE_KMH}
    TRAFFIC_DEFAULT_LANES=${TRAFFIC_DEFAULT_LANES}
    # Feature / Performance Flags
    TRAFFIC_DISABLE_ROUTER_BPR=${DISABLE_BPR_VAL}
    TRAFFIC_ENABLE_ROUTER_PROFILE=${ROUTER_PROFILE_VAL}
)
