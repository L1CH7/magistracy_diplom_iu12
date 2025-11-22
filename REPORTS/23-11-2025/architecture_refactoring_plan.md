# Анализ архитектуры: дублирование src/ vs services/

## Текущее состояние

### Архитектура проекта (2 поколения кода)

```
diplom/
├── src/                    # Поколение 1: монолитный код
│   ├── client/            # ✅ ИСПОЛЬЗУЕТСЯ (PyQt5 GUI)
│   ├── data/              # ⚠️ ИСПОЛЬЗУЕТСЯ legacy server + data-processor
│   ├── routing/           # ❌ НЕ ИСПОЛЬЗУЕТСЯ (заменён services/router)
│   ├── server/            # ⚠️ LEGACY для GUI compatibility
│   │   └── app.py         # 2120 строк монолита (старый API)
│   ├── simulation/        # ❌ НЕ ИСПОЛЬЗУЕТСЯ (заменён services/simulation)
│   ├── shared/            # ✅ ИСПОЛЬЗУЕТСЯ микросервисами
│   └── utils/             # ✅ ИСПОЛЬЗУЕТСЯ всеми
│
├── services/              # Поколение 2: микросервисы
│   ├── simulation/        # ✅ 20 FPS physics engine (port 8001)
│   ├── coordinator/       # ✅ route orchestration + WebSocket (port 8002)
│   ├── router/            # ✅ K-shortest paths (port 8003)
│   ├── traffic-manager/   # ✅ congestion tracking (port 8004)
│   └── data-processor/    # ✅ OSM downloads + MVT (port 8005)
│
└── docker-compose.yml     # 7 контейнеров (postgis, redis, 5 микросервисов + legacy)
```

### Таблица использования модулей

| Модуль | Используется | Где | Статус |
|--------|-------------|-----|--------|
| `src/client/` | ✅ | GUI (PyQt5) | **KEEP** |
| `src/data/` | ⚠️ | legacy server, data-processor | **SHARED** |
| `src/routing/` | ❌ | НИГДЕ | **DELETE** |
| `src/server/app.py` | ⚠️ | Legacy API (GUI /osm/fetch_road_graph) | **REFACTOR** |
| `src/simulation/agent.py` | ❌ | Заменён на src/shared/agent/ | **DELETE** |
| `src/shared/` | ✅ | Все микросервисы | **KEEP** |
| `src/utils/` | ✅ | Все сервисы | **KEEP** |
| `services/*` | ✅ | Docker containers | **KEEP** |

## Проблемы дублирования

### 1. Routing (2 реализации)

**Старый**: `src/routing/` (NetworkX + pgRouting)
- `graph.py` - Graph class, load_from_db
- `pathfinding.py` - A*, Dijkstra
- `route_builder.py` - build_routes() с K-best
- `route_engine.py` - RouteEngine ABC
- `simple_engine.py` - SimpleRouteEngine (nx.shortest_path)

**Новый**: `services/router/` (pgRouting only)
- `manager.py` - RouterManager (asyncpg pool)
- `models.py` - Pydantic models
- Использует SQL function `graphs.get_k_routes_with_diversity()`

**Решение**: УДАЛИТЬ `src/routing/`, т.к. services/router работает + старый код не используется.

### 2. Simulation (2 реализации)

**Старый**: `src/simulation/agent.py` (SimulationAgent)
- Хранится в `src/server/app.py` (legacy)
- Используется только legacy server для GUI

**Новый**: `src/shared/agent/` + `services/simulation/`
- AgentBatch (numpy vectorization)
- SimulationManager (20 FPS loop)
- Используется в production

**Решение**: УДАЛИТЬ `src/simulation/`, перенести SimulationAgent в src/server/ (если нужен для legacy).

### 3. Data Processing (shared код)

**Общий код**: `src/data/`
- `osm_loader.py` - fetch_osm, save_json
- `osm_overpass.py` - Overpass API client
- `osm_profile.py` - OSRM car profile
- `graph_builder.py` - build_graph_from_overpass
- `postgis_manager.py` - PostGISManager (DB queries)

**Используется**:
- `services/data-processor/` - для загрузки OSM
- `src/server/app.py` - для legacy /osm/fetch_road_graph

**Решение**: ОСТАВИТЬ как есть (shared library), но:
- Добавить `src/data/__init__.py` с чистыми экспортами
- Документировать, что это shared код

### 4. Legacy Server (монолит 2120 строк)

**Проблема**: `src/server/app.py` дублирует функционал микросервисов:
- `/routes` - расчёт маршрутов (дубль services/router)
- `/agent/start`, `/sim/agent/*` - симуляция агентов (дубль services/simulation)
- `/osm/fetch_road_graph` - ЕДИНСТВЕННАЯ нужная ручка для GUI!

**Используется GUI**:
- ✅ `/osm/fetch_road_graph` - загрузка OSM для карты (NDJSON stream)
- ❌ Всё остальное - не используется (GUI работает с services/coordinator)

**Решение**: 
- Создать минимальный `services/map-api/` только для GUI (порт 8000)
- Перенести `/osm/fetch_road_graph` + кэш (PostGIS processed_geojson)
- УДАЛИТЬ остальные 90% src/server/app.py

## План рефакторинга

### Этап 1: Удаление мёртвого кода (безопасно)

```bash
# 1. Удалить старый routing (полностью заменён)
rm -rf src/routing/

# 2. Удалить старую симуляцию (заменена на shared/agent)
rm -rf src/simulation/

# 3. Проверить импорты (не должно остаться)
grep -rn "from src.routing" --include="*.py" .
grep -rn "from src.simulation" --include="*.py" .
```

**Ожидаемый результат**: -800 строк кода.

### Этап 2: Рефакторинг legacy server

**Создать**: `services/map-api/` (минимальный API для GUI)

```python
# services/map-api/src/main.py
from fastapi import FastAPI
from src.data.postgis_manager import PostGISManager

app = FastAPI(title="Map API for GUI")

@app.post("/osm/fetch_road_graph")
async def fetch_road_graph(req: RoadGraphRequest):
    """Единственная ручка для GUI - загрузка OSM tiles."""
    # Переносим ТОЛЬКО fetch_road_graph логику
    # Остальное - DELETE
    pass
```

**Удалить**: `src/server/app.py` (90% кода не используется)

**Сохранить**: 
- Кэш logic (PostGIS processed_geojson)
- NDJSON streaming
- Tile fetching (chunked downloads)

**Ожидаемый результат**: -1800 строк, +200 строк (новый map-api).

### Этап 3: Организация shared кода

**Shared библиотеки** (используются несколькими сервисами):

```
src/
├── shared/              # Shared между микросервисами
│   ├── agent/          # AgentBatch, move_batch (simulation)
│   ├── models/         # Pydantic models (общие)
│   └── utils/          # Helpers
│
├── data/               # Shared OSM processing
│   ├── osm_loader.py
│   ├── osm_overpass.py
│   ├── postgis_manager.py
│   └── graph_builder.py
│
├── utils/              # Общие утилиты
│   ├── config_loader.py
│   ├── project_root.py
│   └── logger.py
│
└── client/             # GUI (отдельное приложение)
```

**Правило**: 
- Если код используется >1 сервисом → `src/shared/` или `src/data/`
- Если код специфичен для сервиса → `services/{name}/src/`

### Этап 4: Docker Compose cleanup

**Удалить**: `server` контейнер (legacy)

**Добавить**: `map-api` контейнер (порт 8000)

```yaml
services:
  map-api:  # Заменяет legacy server
    build:
      context: .
      dockerfile: services/map-api/Dockerfile
    ports:
      - "8000:8000"  # GUI expects port 8000
    environment:
      POSTGRES_HOST: postgis
    volumes:
      - ./configs:/app/configs:ro
```

## Итоговая архитектура (после рефакторинга)

```
diplom/
├── src/
│   ├── client/          # GUI (PyQt5) - отдельное приложение
│   ├── data/            # Shared OSM processing (osm_loader, postgis_manager)
│   ├── shared/          # Shared между микросервисами (agent, models, utils)
│   └── utils/           # Общие утилиты (config_loader, logger)
│
├── services/            # Микросервисы (каждый в Docker container)
│   ├── simulation/      # 20 FPS physics engine
│   ├── coordinator/     # Route orchestration + WebSocket
│   ├── router/          # K-shortest paths (pgRouting)
│   ├── traffic-manager/ # Congestion tracking (Redis)
│   ├── data-processor/  # OSM downloads + MVT generation
│   └── map-api/         # GUI map API (минимальный, /osm/fetch_road_graph)
│
├── configs/             # YAML конфиги (shared)
├── migrations/          # PostgreSQL schemas
└── docker-compose.yml   # 7 контейнеров
```

### Принципы разделения

1. **Микросервисы** (`services/`) - изолированные, со своим state:
   - Каждый в отдельном Docker container
   - Своя FastAPI app, manager, models
   - HTTP API между сервисами

2. **Shared библиотеки** (`src/shared/`, `src/data/`, `src/utils/`):
   - Stateless код, переиспользуемый
   - Импортируется микросервисами
   - Монтируется в Docker volumes

3. **GUI** (`src/client/`) - отдельное приложение:
   - PyQt5, не в контейнере
   - Общается с микросервисами через HTTP + WebSocket

## Метрики рефакторинга

### До рефакторинга:
- Всего строк кода: ~15000
- Дублирование: ~2600 строк (routing + simulation + server)
- Контейнеров: 7 (postgis, redis, 5 микросервисов + legacy)

### После рефакторинга:
- Всего строк кода: ~12200 (-2800 строк)
- Дублирование: 0 строк
- Контейнеров: 7 (заменили legacy на map-api)
- Ясность: каждый сервис имеет чёткую зону ответственности

## Следующие шаги

1. ✅ **Создать ARCHITECTURE.md** с итоговой архитектурой
2. ⚠️ **Проверить импорты** перед удалением src/routing/
3. ⚠️ **Создать services/map-api/** для GUI
4. ⚠️ **Удалить src/routing/, src/simulation/, 90% src/server/app.py**
5. ✅ **Обновить docker-compose.yml** (legacy → map-api)
6. ✅ **Создать mermaid диаграммы** (архитектура, API взаимодействие)

## Риски

### Критичные проверки:

1. **GUI зависимости** от legacy server:
   - ✅ Проверено: GUI использует ТОЛЬКО `/osm/fetch_road_graph`
   - ⚠️ Проверить перед удалением: нет ли других ручек?

2. **Shared код** (`src/data/`):
   - ✅ Используется data-processor + map-api
   - ⚠️ Убедиться, что импорты не сломаются

3. **Docker volumes**:
   - ✅ `./src/data` монтируется в data-processor
   - ✅ `./src/utils` монтируется в data-processor
   - ⚠️ Проверить, что все shared модули доступны

### План проверки:

```bash
# 1. Найти все импорты src/routing, src/simulation
grep -rn "from src.routing" --include="*.py" .
grep -rn "from src.simulation" --include="*.py" .

# 2. Найти все обращения к legacy server (кроме /osm/fetch_road_graph)
grep -rn "localhost:8000" --include="*.py" src/client/

# 3. Проверить Docker volume mounts
grep -A5 "volumes:" docker-compose.yml | grep "src/"
```

## Выводы

**Архитектурная проблема**: Проект содержит 2 поколения кода:
- **Поколение 1** (монолит): `src/routing/`, `src/simulation/`, `src/server/app.py`
- **Поколение 2** (микросервисы): `services/*`

**Решение**: Удалить Поколение 1 (кроме shared библиотек), оставить только микросервисы.

**Результат**: Чистая архитектура, 0 дублирования, -2800 строк мёртвого кода.
