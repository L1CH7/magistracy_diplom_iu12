# ---------------------------------------------------------------------------
# EXECUTABLE: GRAPH BUILDER
# ---------------------------------------------------------------------------
# Офлайн-пайплайн генерации графа из БД (Stage 0-4)

# Поиск PostgreSQL и pqxx
find_package(PostgreSQL REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(Threads REQUIRED)
pkg_check_modules(PQXX REQUIRED libpqxx)

add_executable(traffic_graph_builder
    main.cpp
    pipeline_manager.cpp
    sql_orchestrator.cpp
    binary_dumper.cpp
)

target_include_directories(traffic_graph_builder PRIVATE
    .
    ..
    ../common
    ${PostgreSQL_INCLUDE_DIRS}
    ${PQXX_INCLUDE_DIRS}
)

# Интеграция с pqxx и quill
target_link_libraries(traffic_graph_builder PRIVATE
    ${PostgreSQL_LIBRARIES}
    ${PQXX_LIBRARIES}
    quill::quill
    concurrentqueue
    Threads::Threads
)
