# --- STAGE 1: Сборка (Жирный образ) ---
FROM gcc:14 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Ставим всё для компиляции (Boost, libpqxx, CMake)
RUN apt-get update && apt-get install -y \
    cmake \
    git \
    ninja-build \
    libnuma-dev \
    libpqxx-dev \
    libboost-dev \
    libzmq3-dev \
    cppzmq-dev \
    postgresql-server-dev-all \
    ccache \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/traffic_core /app/services/traffic_core

WORKDIR /app/services/traffic_core/build

# Компилируем оба бинарника: traffic_core и traffic_graph_builder
RUN --mount=type=cache,target=/root/.cache/ccache \
    cmake -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER_LAUNCHER=ccache .. && \
    cmake --build .

# --- СТЕЙДЖ ЗАПУСКА (RUNTIME) ---

# ВРЕМЕННО: Используем Debian Slim для активной разработки и отладки
# В нем есть bash, ls, tail и другие инструменты для проверки mmap и логов
FROM debian:trixie-slim AS runtime

# ФИНАЛЬНЫЙ ВАРИАНТ: Раскомментируй строку ниже и удали/закомментируй Debian Slim для релиза
# Образ distroless/cc содержит только glibc, libgcc и libstdc++, без шелла и лишнего мусора
# FROM gcr.io/distroless/cc-debian12 AS runtime

# Устанавливаем libnuma для Thread Affinity и postgres deps
RUN apt-get update && apt-get install -y \
    libnuma1 \
    libpq5 \
    libpqxx-dev \
    libzmq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем скомпилированные бинарники из стейджа сборки (builder)
COPY --from=builder /app/services/traffic_core/build/src/modules/daemon/traffic_daemon .
COPY --from=builder /app/services/traffic_core/build/src/graph_builder/traffic_graph_builder .

ENTRYPOINT ["./traffic_daemon"]
CMD ["/app/data"]
