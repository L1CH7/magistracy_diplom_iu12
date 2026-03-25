FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Установка зависимостей сборки
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    ninja-build \
    libnuma-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/traffic_core /app/services/traffic_core

WORKDIR /app/services/traffic_core/build

# Сборка Release с HFT оптимизациями
RUN cmake -G Ninja -DCMAKE_BUILD_TYPE=Release .. && \
    cmake --build .

FROM ubuntu:24.04 AS runtime

# Устанавливаем libnuma для корректной работы Thread Affinity в C++
RUN apt-get update && apt-get install -y libnuma1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/services/traffic_core/build/traffic_core /app/traffic_core

ENTRYPOINT ["/app/traffic_core"]
