# Makefile для управления проектом

.PHONY: help build build-% up up-% down restart logs logs-% ps health migrate gui clean

help:
	@echo "Доступные команды:"
	@echo "  make build        - Сборка всех контейнеров"
	@echo "  make build-%      - Сборка конкретного контейнера (make build-simulation)"
	@echo "  make up           - Запуск всех сервисов"
	@echo "  make up-%         - Запуск конкретного сервиса"
	@echo "  make down         - Остановка всех сервисов"
	@echo "  make restart      - Рестарт всех сервисов"
	@echo "  make logs         - Просмотр логов всех сервисов"
	@echo "  make logs-%       - Логи конкретного сервиса (make logs-simulation)"
	@echo "  make ps           - Статус контейнеров"
	@echo "  make health       - Проверка health всех сервисов"
	@echo "  make migrate      - Применить миграции БД"
	@echo "  make gui          - Запуск GUI локально"
	@echo "  make clean        - Удалить все контейнеры и volumes"

# Сборка с кэшем и параллелизацией
build:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build --parallel

build-%:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build $*

# Запуск сервисов
up:
	docker compose up -d

up-%:
	docker compose up -d $*

# Остановка
down:
	docker compose down

# Рестарт
restart:
	docker compose restart

# Логи
logs:
	docker compose logs --tail=100 -f

logs-%:
	docker compose logs --tail=100 -f $*

# Статус
ps:
	docker compose ps

# Health check
health:
	@echo "Проверка health endpoints..."
	@curl -f http://localhost:8001/health 2>/dev/null && echo "✓ Simulation OK" || echo "✗ Simulation FAIL"
	@curl -f http://localhost:8002/health 2>/dev/null && echo "✓ Coordinator OK" || echo "✗ Coordinator FAIL"
	@curl -f http://localhost:8003/health 2>/dev/null && echo "✓ Router OK" || echo "✗ Router FAIL"
	@curl -f http://localhost:8004/health 2>/dev/null && echo "✓ Traffic Manager OK" || echo "✗ Traffic Manager FAIL"
	@curl -f http://localhost:8005/health 2>/dev/null && echo "✓ Data Processor OK" || echo "✗ Data Processor FAIL"

# Миграции
migrate:
	@echo "Применение миграций..."
	docker compose exec postgis psql -U diplom -d osm -f /docker-entrypoint-initdb.d/010_simulation_functions.sql
	docker compose exec postgis psql -U diplom -d osm -f /docker-entrypoint-initdb.d/011_router_functions.sql
	@echo "Миграции применены"

# GUI локально (не в контейнере)
gui:
	@echo "Запуск GUI локально..."
	cd src/client && python3 main.py

# Очистка
clean:
	docker compose down -v
	docker system prune -f
