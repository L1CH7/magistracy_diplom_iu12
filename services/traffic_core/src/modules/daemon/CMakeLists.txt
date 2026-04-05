add_executable(traffic_daemon
    src/traffic_daemon.cpp
)

target_include_directories(traffic_daemon PRIVATE 
    ../../modules/core/include 
    ../../modules/router/include 
    ../../modules/data_provider/include
    ../../modules/decision_engine/include
    ../../common
    ../../
)

target_link_libraries(traffic_daemon PRIVATE
    traffic_core_core
    traffic_router
    traffic_data_provider
    traffic_decision_engine
    concurrentqueue
    ZMQ::ZMQ
)
