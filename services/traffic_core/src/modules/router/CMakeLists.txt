# ---------------------------------------------------------------------------
# MODULE: ROUTER
# ---------------------------------------------------------------------------
# Разделение на Control Plane (C++26) и Compute Plane (Brutal Optimizations)

# 1. Compute Plane (A* и эвристики - бывший hot_loop)
add_library(traffic_router_compute INTERFACE) # Заменить на OBJECT/STATIC когда появятся .cpp
target_include_directories(traffic_router_compute INTERFACE 
    include
    ${CMAKE_SOURCE_DIR}/src
)
target_link_libraries(traffic_router_compute INTERFACE quill::quill)
# Жестокие оптимизации только для вычислительного ядра:

# 2. Control Plane (C++26 управление, интерфейсы - бывший cxx26)
add_library(traffic_router_control STATIC 
    src/control/router_manager.cpp
)
target_include_directories(traffic_router_control PUBLIC 
    include
    ${CMAKE_SOURCE_DIR}/src
)
# target_compile_options(traffic_router_control PRIVATE -O3 -march=native -mavx2 -flto -fno-rtti) # Global instead
target_link_libraries(traffic_router_control PRIVATE quill::quill)

# 3. Фасадный таргет модуля
add_library(traffic_router INTERFACE)
target_link_libraries(traffic_router INTERFACE 
    traffic_router_compute 
    traffic_router_control
)
