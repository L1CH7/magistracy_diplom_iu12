# Makefile для управления проектом через make

.PHONY: xhost build build-% up down logs

xhost:
	xhost +local:docker

# Build all or specific containers (Buildroot style)
build:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build --parallel

build-%:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build $* --parallel

# Start services
up: xhost
	docker compose up -d

down:
	docker compose down

# Logs (deprecated - use structured logs instead)
logs:
	@echo "WARNING: Use structured log queries instead of docker logs"
	@echo "Example: docker compose exec postgis psql -U diplom -d road_graphs -c \"SELECT * FROM logs ORDER BY timestamp DESC LIMIT 50;\""
	docker compose logs --tail=100
