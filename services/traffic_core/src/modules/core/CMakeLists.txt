add_library(traffic_core_core STATIC
    src/traffic_engine.cpp
    src/telemetry_worker.cpp
)

target_include_directories(traffic_core_core PUBLIC include)
target_include_directories(traffic_core_core PRIVATE ../../../../src) # for common and other modules

target_link_libraries(traffic_core_core PUBLIC
    traffic_router
    traffic_data_provider
    traffic_decision_engine
    concurrentqueue
    ZMQ::ZMQ
)
