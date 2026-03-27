# ---------------------------------------------------------------------------
# EXECUTABLE: GRAPH BUILDER
# ---------------------------------------------------------------------------
# Офлайн-пайплайн генерации графа из БД (Stage 0-4)

# Поиск PostgreSQL, pqxx и OpenMP
find_package(PostgreSQL REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(Threads REQUIRED)
find_package(OpenMP REQUIRED)
pkg_check_modules(PQXX REQUIRED libpqxx)

add_executable(traffic_graph_builder
    main.cpp
    pipeline_manager.cpp
    sql_orchestrator.cpp
    binary_dumper.cpp
    landmarks.cpp
)

target_include_directories(traffic_graph_builder PRIVATE
    .
    ..
    ../common
    ${PostgreSQL_INCLUDE_DIRS}
    ${PQXX_INCLUDE_DIRS}
)

# Интеграция с pqxx, quill и OpenMP
target_link_libraries(traffic_graph_builder PRIVATE
    ${PostgreSQL_LIBRARIES}
    ${PQXX_LIBRARIES}
    quill::quill
    concurrentqueue
    Threads::Threads
    OpenMP::OpenMP_CXX
)

target_compile_options(traffic_graph_builder PRIVATE ${OpenMP_CXX_FLAGS})
