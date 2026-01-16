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

# Build Qt Client (Create venv and install deps)
build-gui:
	@echo "Setting up Qt Client environment..."
	cd services/qt-client && python3 -m venv .venv && \
	. .venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt

# Run the Qt Client
gui:
	@echo "Starting Qt Client..."
	PYTHONPATH=. services/qt-client/.venv/bin/python services/qt-client/main.py

# Clean up docker resources
clean:
	docker-compose down -v
	rm -rf services/web-client/dist
	rm -rf services/web-client/node_modules

# Help command to list targets
help:
	@echo "Available commands:"
	@echo "  make build          - Build all services in parallel"
	@echo "  make up             - Start all services in background"
	@echo "  make down           - Stop all services"
	@echo "  make logs           - Follow logs of all services"
	@echo "  make logs-<service> - Follow logs of specific service (e.g. make logs-router)"
	@echo "  make restart        - Restart all services"
	@echo "  make shell-<service>- Open bash shell in service container"
	@echo "  make gui            - Run local Qt client"
	@echo "  make clean          - Deep clean (remove volumes, orphans)"
