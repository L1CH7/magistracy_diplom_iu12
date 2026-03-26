# ---------------------------------------------------------------------------
# EXECUTABLE: GRAPH BUILDER
# ---------------------------------------------------------------------------
# Офлайн-пайплайн генерации графа из БД (Stage 0-4)

# Поиск PostgreSQL и pqxx
find_package(PostgreSQL REQUIRED)
# Для pqxx в Ubuntu обычно используется пакетная установка, ищем через pkg-config
find_package(PkgConfig REQUIRED)
pkg_check_modules(PQXX REQUIRED libpqxx)

add_executable(traffic_graph_builder
    main.cpp
    db_orchestrator.cpp
)

target_include_directories(traffic_graph_builder PRIVATE 
    . 
    ..
    ${PostgreSQL_INCLUDE_DIRS} 
    ${PQXX_INCLUDE_DIRS}
)

# Интеграция с pqxx и quill
target_link_libraries(traffic_graph_builder PRIVATE
    ${PostgreSQL_LIBRARIES}
    ${PQXX_LIBRARIES}
    quill::quill
    concurrentqueue
)
