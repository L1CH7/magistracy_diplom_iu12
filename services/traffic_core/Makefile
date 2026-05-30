.PHONY: build build-builder run-builder test-integration test-functional algorithms-comparison

# Параметры хранения данных
DATA_VOLUME ?= traffic_data
# Раскомментируйте строку ниже, чтобы переключиться на локальную папку
# DATA_VOLUME := $(shell pwd)/data

# Базовый образ для сборки и тестов
BUILDER_IMAGE = traffic_core_builder

build-builder:
	@echo ">>> Building builder image (using docker cache)..."
	@DOCKER_BUILDKIT=1 docker build --target builder -t $(BUILDER_IMAGE) -f Dockerfile ../..

run-builder: build-builder
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		-e APP__DB__HOST=localhost \
		-e APP__DB__PORT=5432 \
		-e APP__DB__USER=postgres \
		-e APP__DB__PASSWORD=postgres \
		-e APP__DB__NAME=nav_mas \
		$(BUILDER_IMAGE) /app/services/traffic_core/build/src/graph_builder/traffic_graph_builder $(ARGS)

build-release:
	@echo ">>> Building release image..."
	DOCKER_BUILDKIT=1 docker build -t traffic_core -f Dockerfile ../..

run-router: build-release
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		traffic_core /app/data

# --- Тестирование ---

test-functional:
	@echo ">>> Running native C++ functional tests..."
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		$(BUILDER_IMAGE) /app/services/traffic_core/build/test_functional

test-integration:
	@echo ">>> Running Python Integration Tests (API & Protocol)..."
	pytest tests/test_integration.py -s $(ARGS)

# --- Бенчмарки ---

THREADS ?= 12
AFFINITY ?= 1
AVOID_OS ?= 1

throughput-bench:
	@mkdir -p $(HOME)/.ccache_docker
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		-v $(HOME)/.ccache_docker:/root/.cache/cache \
		$(BUILDER_IMAGE) /app/services/traffic_core/build/throughput_benchmark \
			--data /app/data \
			--threads $(THREADS) \
			--affinity $(AFFINITY) \
			--avoid-os $(AVOID_OS)

pq-bench: build-builder
	docker run --rm --init --network host \
		$(BUILDER_IMAGE) taskset -c 0 /app/services/traffic_core/build/pq_benchmark

pq-comparison: build-builder
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		$(BUILDER_IMAGE) taskset -c 0 /app/services/traffic_core/build/router_pq_comparison --data /app/data

algorithms-comparison: build-builder
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		$(BUILDER_IMAGE) taskset -c 0 /app/services/traffic_core/build/router_algorithms_comparison \
			--data /app/data \
			--out /app/benchmark/traffic-core/stats/run_results.csv


simulation-benchmark: build-builder
	docker run --rm --init --network host \
		-v $(DATA_VOLUME):/app/data \
		$(BUILDER_IMAGE) /app/services/traffic_core/build/simulation_benchmark $(ARGS)
