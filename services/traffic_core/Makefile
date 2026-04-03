.PHONY: build build-builder run-builder

build-builder:
	DOCKER_BUILDKIT=1 docker build --target builder -t traffic_core_builder -f Dockerfile ../..

run-builder: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		-e APP__DB__HOST=localhost \
		-e APP__DB__PORT=5432 \
		-e APP__DB__USER=postgres \
		-e APP__DB__PASSWORD=postgres \
		-e APP__DB__NAME=nav_mas \
		traffic_core_builder /app/services/traffic_core/build/src/graph_builder/traffic_graph_builder $(ARGS)

build-release:
	DOCKER_BUILDKIT=1 docker build -t traffic_core -f Dockerfile ../..

run-router: build-release
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core /app/data

test-router: run-router

THREADS ?= 12
AFFINITY ?= 1
AVOID_OS ?= 1

throughput-bench: build-builder
	mkdir -p $(HOME)/.ccache_docker
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		-v $(HOME)/.ccache_docker:/root/.cache/ccache \
		traffic_core_builder /app/services/traffic_core/build/throughput_benchmark \
			--data /app/data \
			--threads $(THREADS) \
			--affinity $(AFFINITY) \
			--avoid-os $(AVOID_OS)

test-functional: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core_builder /app/services/traffic_core/build/test_functional

pq-bench: build-builder
	docker run --rm --init --network host \
		traffic_core_builder taskset -c 0 /app/services/traffic_core/build/pq_benchmark

pq-comparison: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core_builder taskset -c 0 /app/services/traffic_core/build/router_pq_comparison --data /app/data

# Simulation Benchmark
AGENTS ?= 100000
ASF ?= 1
ACCEL ?= 1
DURATION ?= 600

simulation-benchmark: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core_builder /app/services/traffic_core/build/simulation_benchmark \
			--agents $(AGENTS) \
			--asf $(ASF) \
			--accel $(ACCEL) \
			--duration $(DURATION)
