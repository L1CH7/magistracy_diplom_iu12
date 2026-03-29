.PHONY: build build-builder run-builder

build-builder:
	docker build --target builder -t traffic_core_builder -f Dockerfile ../..

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
	docker build -t traffic_core -f Dockerfile ../..

run-router: build-release
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core /app/data

test-router: run-router

throughput-bench: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core_builder /app/services/traffic_core/build/throughput_benchmark --data /app/data

test-dynamic: build-builder
	docker run --rm --init --network host \
		-v $(shell pwd)/data:/app/data \
		traffic_core_builder /app/services/traffic_core/build/test_functional

pq-bench: build-builder
	docker run --rm --init --network host \
		traffic_core_builder /app/services/traffic_core/build/pq_benchmark
