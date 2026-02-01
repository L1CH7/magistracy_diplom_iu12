.PHONY: all build up down logs restart clean prune shell-gateway shell-router shell-data help gui

# Default target
all: help

# Build all services with parallel execution
build:
	docker-compose build --parallel

# Build specific service
build-%:
	docker-compose build $*

# Start services in detached mode (recreates containers if config changed)
up:
	docker-compose up -d --remove-orphans

# Start specific service
up-%:
	docker-compose up -d $*

# Stop all services
down:
	docker-compose down

# Stop and remove volumes
down-v:
	docker-compose down -v

# Show logs for all services
logs:
	docker-compose logs -f

# Show logs for specific service
logs-%:
	docker-compose logs -f $*

# Restart all services
restart: down up

# Restart specific service
restart-%:
	docker-compose restart $*

# Clean up docker resources (prune stopped containers and unused images)
prune:
	docker system prune -f

# Open shell in gateway
shell-gateway:
	docker-compose exec gateway /bin/bash

# Open shell in router
shell-router:
	docker-compose exec router /bin/bash

# Open shell in data-processor
shell-data:
	docker-compose exec data-processor /bin/bash

# ==============================================================================
# GUI Client Targets
# ==============================================================================

# Сборка: Установка -> Генерация .ts -> Компиляция .qm
build-gui:
	$(MAKE) -C services/qt-client install translate compile

# Запуск приложения
gui:
	$(MAKE) -C services/qt-client run

# Полная пересборка с нуля (удаление venv и кэшей)
build-clean-gui:
	$(MAKE) -C services/qt-client clean
	$(MAKE) build-gui

# Clean up docker resources
clean:
	docker-compose down -v
	rm -rf services/web-client/dist
	rm -rf services/web-client/node_modules
	$(MAKE) -C services/qt-client clean

# ==============================================================================
# Testing & Benchmarking (Elegant Docker Approach)
# ==============================================================================

.PHONY: test bench shell

# Запуск функциональных тестов маршрутизации
test:
	docker-compose run --rm router pytest -v tests/test_routing.py

# Запуск бенчмарков производительности
# Scientific Benchmarking (v3 - Metric Groups)
# Scientific Benchmarking (v3 - Metric Groups)
NUM_SAMPLES ?= 1000
NUM_WORKERS_THROUGHPUT ?= 50

bench-latency: ## 1. Sequential Latency Test (Default 1000, can override)
	@echo "Running Latency Benchmark (Sequential)..."
	docker-compose run --rm -v $(PWD)/benchmarks:/app/benchmarks \
		-e NUM_SAMPLES=$(NUM_SAMPLES) -e BENCHMARK_PREFIX=latency_results router \
		pytest -v tests/test_benchmark.py

bench-throughput: ## 2. Parallel Throughput Test (Default 1000 samples, 50 threads)
	@echo "Running Throughput Benchmark ($(NUM_WORKERS_THROUGHPUT) threads pool)..."
	docker-compose run --rm -v $(PWD)/benchmarks:/app/benchmarks \
		-e NUM_SAMPLES=$(NUM_SAMPLES) -e NUM_WORKERS=$(NUM_WORKERS_THROUGHPUT) \
		-e BENCHMARK_PREFIX=throughput_results router \
		pytest -n $(NUM_WORKERS_THROUGHPUT) tests/test_benchmark.py

plot: ## 3. Generate Russian Plots
	@echo "Generating projections and variance plots..."
	PYTHON_BIN=.venv/bin/python3; \
	$$PYTHON_BIN benchmarks/scripts/analyze.py

clean-bench: ## Clean all benchmark data
	rm -rf benchmarks/router

# Для отладки: запускаем bash внутри окружения
shell:
	docker-compose run --rm --entrypoint /bin/bash router

# Help command to list targets
help:
	@echo "Available commands:"
	@echo "  make build             - Build all services"
	@echo "  make up                - Start all services"
	@echo "  make test              - Run functional tests"
	@echo "  make dataset           - Generate valid routes for benchmarks"
	@echo "  make bench-latency     - Run algorithm latency test (1 thread)"
	@echo "  make bench-throughput  - Run system stress test (12 threads)"
	@echo "  make plot              - Generate scientific plots"
	@echo "  make clean-bench       - Remove CSV results, plots and dataset"
	@echo "  make gui               - Run local Qt client"
