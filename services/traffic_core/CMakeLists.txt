cmake_minimum_required(VERSION 3.20)
project(nav_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Оптимизации для HFT/DoD
if(CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    add_compile_options(-O3 -march=native -flto -fno-rtti)
    # Zero-Cost абстракция: вырезаем уровни логирования TRACE и DEBUG из сборки (compile-time)
    add_compile_definitions(QUILL_ACTIVE_LOG_LEVEL=QUILL_LOG_LEVEL_INFO)
else()
    add_compile_definitions(QUILL_ACTIVE_LOG_LEVEL=QUILL_LOG_LEVEL_TRACE_L3)
endif()

# Интеграция слоя логирования (Quill как submodule)
add_subdirectory(3rd_party/quill)

# Изолированные подмодули
add_subdirectory(src/modules/router)
add_subdirectory(src/modules/data_provider)
add_subdirectory(src/modules/decision_engine)

add_executable(nav_core
    src/main.cpp
)

target_include_directories(nav_core PRIVATE src)

# Композиция
target_link_libraries(nav_core PRIVATE
    quill::quill
    traffic_router
    traffic_data_provider
    traffic_decision_engine
)
