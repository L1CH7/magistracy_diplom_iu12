# Makefile для управления проектом через make

.PHONY: xhost client server build up down logs

xhost:
	xhost +local:docker

build:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build --parallel

up: xhost
	docker compose up -d

client:
	docker compose up -d diplom-client

server:
	docker compose up -d diplom-server

down:
	docker compose down

logs:
	docker compose logs --tail=100
