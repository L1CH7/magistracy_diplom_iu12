cmake_minimum_required(VERSION 3.20)
project(traffic_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Включаем опции компиляции (Runtime Config и Compile-time Constants)
include(cmake/options.cmake)

# Глобальные оптимизации для HFT Hot Path (согласно стандарту кодирования)
if(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    add_compile_options(-O3 -march=native -mavx2 -flto)
    add_link_options(-flto)
    add_compile_definitions(QUILL_ACTIVE_LOG_LEVEL=${QUILL_COMPILE_ACTIVE_LOG_LEVEL})
else()
    add_compile_definitions(QUILL_ACTIVE_LOG_LEVEL=QUILL_LOG_LEVEL_TRACE_L3)
endif()

# Интеграция 3rd party
add_subdirectory(3rd_party/quill)
add_subdirectory(3rd_party/concurrentqueue)

# ============================
# MODULES (Архитектура системы)
# ============================
add_subdirectory(src/modules/router)
add_subdirectory(src/modules/data_provider)
add_subdirectory(src/modules/decision_engine)

# ============================
# EXECUTABLE: TRAFFIC CORE
# ============================
add_executable(traffic_core
    src/main.cpp
)

target_include_directories(traffic_core PRIVATE src)

# Композиция архитектуры
target_link_libraries(traffic_core PRIVATE
    quill::quill
    concurrentqueue
    traffic_router
    traffic_data_provider
    traffic_decision_engine
)

# ============================
# EXECUTABLE: GRAPH BUILDER (Offline)
# ============================
add_subdirectory(src/graph_builder)


# ============================
# TESTS
# ============================
option(TRAFFIC_BUILD_TESTS "Build unit and functional tests" ON)

if(TRAFFIC_BUILD_TESTS)
    add_executable(test_functional tests/test_functional.cpp)
    target_include_directories(test_functional PRIVATE 
        src/modules/router/include 
        src/modules/data_provider/include
        src/modules/decision_engine/include
        src/common
        src
        3rd_party/doctest
    )
    target_link_libraries(test_functional PRIVATE 
        traffic_router
        traffic_data_provider
        traffic_decision_engine
        quill::quill
        concurrentqueue
    )

    add_executable(throughput_benchmark tests/throughput_benchmark.cpp)
    target_include_directories(throughput_benchmark PRIVATE 
        src/modules/router/include 
        src/common
        src
        3rd_party/doctest
    )
    target_link_libraries(throughput_benchmark PRIVATE 
        traffic_router
        quill::quill
        concurrentqueue
    )
endif()
