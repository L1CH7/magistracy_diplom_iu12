# Сборка Rust-библиотеки SimdQuickHeap
if(NOT TARGET simd_quickheap_lib)
    add_custom_target(simd_quickheap_lib
        ALL
        COMMAND cargo build --release
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}/3rd_party/quickheap
        BYPRODUCTS ${CMAKE_SOURCE_DIR}/3rd_party/quickheap/target/release/libsimd_quickheap.a
        COMMENT "Building Rust SimdQuickHeap static library"
    )
endif()

add_library(simd_quickheap STATIC IMPORTED GLOBAL)
set_target_properties(simd_quickheap PROPERTIES
    IMPORTED_LOCATION ${CMAKE_SOURCE_DIR}/3rd_party/quickheap/target/release/libsimd_quickheap.a
)
add_dependencies(simd_quickheap simd_quickheap_lib)

# 1. Compute Plane (A* и эвристики - бывший hot_loop)
add_library(traffic_router_compute INTERFACE) # Заменить на OBJECT/STATIC когда появятся .cpp
target_include_directories(traffic_router_compute INTERFACE 
    include
    ${CMAKE_SOURCE_DIR}/src
)
target_link_libraries(traffic_router_compute INTERFACE quill::quill simd_quickheap)
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
