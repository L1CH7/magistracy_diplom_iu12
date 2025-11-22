# Архитектура МАС: Multi-Agent Navigation System

## Концепция МАС (Multi-Agent System)

### Что такое МАС в нашем проекте?

**МАС (Multi-Agent System)** - система, где множество независимых агентов принимают решения локально и взаимодействуют через общую среду.

**В контексте навигации**:
- **Агент** = один автомобиль (или пользователь с GPS)
- Агенты автономны: принимают решения локально (выбор маршрута, перестроение)
- **Координатор** = сервер, который предоставляет информацию (маршруты, пробки), но НЕ управляет агентами напрямую
- **Симуляция** = тестовая среда для отладки (заменяет реальное движение)

### Реальный мир vs Симуляция

| Аспект | Реальный мир | Симуляция |
|--------|-------------|-----------|
| Агент | Мобильное приложение на телефоне | Виртуальный агент на сервере |
| Координаты | GPS + ГЛОНАСС (реальные) | Расчёт по формуле (синтетические) |
| Движение | Водитель управляет | Физический движок (BPR, acceleration) |
| Маршрут | Пользователь выбирает из K вариантов | То же самое |
| Перемаршрутизация | Пользователь решает (принять/игнорировать) | То же самое |
| Пробки | Реальные данные от других агентов | Synthetic congestion (load/capacity) |

## Текущее состояние кода

### Что ДОДЕЛАНО (Working)

1. **GUI Client** (`src/client/`)
   - ✅ PyQt5 + MapLibre GL JS
   - ✅ Точки маршрута, выбор K альтернатив
   - ✅ Загрузка OSM tiles (/osm/fetch_road_graph)
   - ✅ Отображение маршрутов с цветами по времени
   - ✅ Debugging tools (Ctrl+Shift+D grid, tile redownload)
   - **Статус**: Production-ready

2. **Data Processor** (`services/data-processor/`)
   - ✅ Tile-based OSM downloads (Overpass API)
   - ✅ PostGIS caching (osm.ways, osm.nodes)
   - ✅ MVT generation (ST_AsMVT)
   - ✅ Task manager (stuck tile recovery)
   - **Статус**: Production-ready

3. **PostgreSQL + PostGIS**
   - ✅ schemas: osm, graphs, tiles
   - ✅ ST_AsMVTGeom, ST_TileEnvelope
   - ✅ Tile cache (processed_geojson)
   - **Статус**: Production-ready

4. **Legacy Server** (`src/server/app.py`)
   - ✅ /osm/fetch_road_graph (NDJSON streaming)
   - ✅ /routes (K-best через build_routes)
   - ✅ /sim/agent/* (SimulationAgent movement)
   - ⚠️ Монолит 2120 строк (нужна декомпозиция)
   - **Статус**: Working, но требует рефакторинга

### Что НЕ ДОДЕЛАНО (Sketches)

1. **Router Service** (`services/router/`)
   - ⚠️ RouterManager готов (asyncpg pool, find_nearest_node)
   - ❌ SQL function `graphs.get_k_routes_with_diversity()` НЕ создана
   - ❌ Нет миграции для graphs schema
   - **Статус**: 30% готовности

2. **Simulation Service** (`services/simulation/`)
   - ✅ SimulationManager + AgentBatch (numpy arrays)
   - ✅ 20 FPS tick loop
   - ⚠️ move_batch() реализован, но НЕ тестирован
   - ❌ Нет GraphCache (загрузка edges из БД)
   - ❌ WebSocket broadcast в Coordinator отсутствует
   - **Статус**: 40% готовности

3. **Coordinator Service** (`services/coordinator/`)
   - ✅ CoordinatorManager + HTTP endpoints
   - ❌ calculate_routes() - MOCK (ждёт Router Service)
   - ❌ Rerouting loop НЕ реализован
   - ❌ WebSocket `/ws/positions` готов, но нет broadcast
   - ❌ Нет интеграции с Simulation Service
   - **Статус**: 30% готовности

4. **Traffic Manager Service** (`services/traffic-manager/`)
   - ✅ TrafficManager + Redis cache
   - ❌ SQL function `graphs.get_congestion_stats()` НЕ создана
   - ❌ Нет таблицы для `current_load` (edges нагрузка)
   - ❌ Нет интеграции с Simulation (sync load)
   - **Статус**: 20% готовности

## МАС Архитектура (целевая)

### Где находятся агенты?

**2 режима работы**:

#### Режим 1: Реальный МАС (Production)

```
[Мобильное приложение 1] ──┐
[Мобильное приложение 2] ──┼── HTTP + WS ──> [Coordinator Service]
[Мобильное приложение N] ──┘                         │
                                                      ├──> [Router Service]
                                                      ├──> [Traffic Manager]
                                                      └──> [Data Processor]
```

- **Агент** = мобильное приложение на телефоне пользователя
- Координаты получает от GPS/ГЛОНАСС
- Отправляет координаты в Coordinator (для расчёта пробок)
- Получает K маршрутов от Coordinator
- Принимает решения локально (выбор маршрута, рероутинг)
- **Симуляция не используется** (реальное движение)

#### Режим 2: Виртуальная симуляция (Testing/Demo)

```
[GUI Client] ──> [Legacy Server (app.py)]
                        │
                        ├──> /osm/fetch_road_graph (Data Processor)
                        ├──> /routes (собственный K-routing)
                        └──> /sim/agent/* (SimulationAgent)
                              │
                              └──> Физический движок (BPR, acceleration)

OR (после рефакторинга):

[GUI Client] ──> [Coordinator Service]
                        │
                        ├──> [Router Service] (K-shortest paths)
                        ├──> [Simulation Service] (AgentBatch, 20 FPS)
                        ├──> [Traffic Manager] (congestion tracking)
                        └──> [Data Processor] (OSM tiles, MVT)
```

- **Агент** = виртуальная сущность на сервере (Simulation Service)
- Координаты рассчитываются физическим движком
- Используется для тестирования алгоритмов (K-routing, rerouting, congestion)
- GUI показывает real-time движение (WebSocket)

### Ключевой вопрос: Где должен быть агент?

**Ответ**: Зависит от режима!

| Режим | Агент находится | Координаты | Решения | Цель |
|-------|----------------|------------|---------|------|
| **Реальный МАС** | Мобильное приложение (клиент) | GPS/ГЛОНАСС | Локально на клиенте | Production |
| **Виртуальная симуляция** | Сервер (Simulation Service) | Физический расчёт | Локально на сервере | Testing, Demo |

**Агент НЕ зависит от симуляции** - верно!
- В реальном МАС: агент = клиент с GPS
- В симуляции: агент = виртуальная сущность, движение которой рассчитывает движок

**Симуляция = движок для виртуальных агентов**:
- Используется только для тестирования
- Заменяет реальное GPS-движение синтетическим
- Позволяет тестировать алгоритмы без реальных пользователей

## Архитектурный план (Phase-by-phase)

### Phase 1: Cleanup мёртвого кода (текущий PR)

**Цель**: Удалить код, который НЕ используется и НЕ будет использоваться.

**Что удалить**:
- ❌ `src/routing/` (6 файлов, 46KB) - полностью заменён на services/router
  - Причина: GUI использует legacy server, legacy server имеет СОБСТВЕННЫЙ routing (build_routes)
  - services/router НЕ используется GUI (ещё не подключен)
  - src/routing/ = МЁРТВЫЙ код (дубль)

**Что ОСТАВИТЬ**:
- ✅ `src/simulation/agent.py` - используется legacy server для GUI
- ✅ `src/server/app.py` - legacy API для GUI (2120 строк, нужен рефакторинг в Phase 2)
- ✅ `src/data/` - shared библиотека (OSM processing)
- ✅ `src/shared/` - shared между микросервисами
- ✅ `services/*` - микросервисы (наброски, будут доделаны в Phase 2+)

**Результат Phase 1**:
- Удалено: ~800 строк мёртвого кода
- Архитектура остаётся рабочей
- Создан документ ARCHITECTURE.md с финальной целью

### Phase 2: Доработка микросервисов (следующий PR)

**Цель**: Завершить Router + Simulation + Coordinator до production-ready.

**Router Service**:
1. Создать миграцию для graphs schema
2. Реализовать SQL function `graphs.get_k_routes_with_diversity()`
3. Тестирование на реальных данных (Moscow MKAD)

**Simulation Service**:
1. Реализовать GraphCache (загрузка edges из PostgreSQL)
2. Протестировать move_batch() с реальными маршрутами
3. Добавить WebSocket broadcast в Coordinator

**Coordinator Service**:
1. Интегрировать с Router Service (calculate_routes)
2. Интегрировать с Simulation Service (agent management)
3. Реализовать rerouting loop (hybrid strategy)

**Traffic Manager**:
1. Создать таблицу `graphs.edge_loads` (current_load, timestamp)
2. Реализовать SQL function `graphs.get_congestion_stats()`
3. Sync с Simulation Service (каждые 5 секунд)

**Результат Phase 2**:
- Микросервисы готовы к production
- GUI может переключиться с legacy server на Coordinator

### Phase 3: Миграция GUI на микросервисы

**Цель**: Переключить GUI с legacy server на Coordinator.

**Изменения в GUI**:
1. Заменить `server_url` с `localhost:8000` на `localhost:8002` (Coordinator)
2. Заменить `/routes` на `/api/v1/routes/calculate`
3. Заменить `/sim/agent/*` на Coordinator endpoints
4. Оставить `/osm/fetch_road_graph` на Data Processor (порт 8005)

**Результат Phase 3**:
- GUI работает через микросервисы
- legacy server больше не нужен

### Phase 4: Удаление legacy server

**Цель**: Удалить монолит после успешной миграции.

**Что удалить**:
- ❌ `src/server/app.py` (2120 строк)
- ❌ `src/simulation/agent.py` (используется только legacy server)
- ❌ Docker container `server` (заменён на Coordinator)

**Результат Phase 4**:
- Чистая микросервисная архитектура
- 0 дублирования кода
- -2800 строк мёртвого кода

### Phase 5: Режим реального МАС (будущее)

**Цель**: Создать мобильное приложение для реальных пользователей.

**Компоненты**:
1. **Mobile App** (Flutter/React Native)
   - GPS/ГЛОНАСС трекинг
   - Отправка координат в Coordinator
   - Получение K маршрутов
   - Локальные решения (выбор, рероутинг)

2. **Coordinator API расширение**:
   - `/api/v1/agents/register` - регистрация реального агента
   - `/api/v1/agents/{id}/update_position` - отправка GPS
   - `/api/v1/agents/{id}/routes` - получение K маршрутов
   - WebSocket для real-time уведомлений (пробки, рероутинг)

3. **Traffic Manager**:
   - Расчёт пробок по реальным координатам агентов
   - Обновление `current_load` в БД
   - Redis cache для fast lookups

**Результат Phase 5**:
- Полноценный МАС с реальными пользователями
- Simulation Service используется только для тестирования
- Production-ready навигационная система

## Финальная архитектура (после всех фаз)

```
┌─────────────────────────────────────────────────────────┐
│                   PRODUCTION MODE                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [Mobile App 1] ──┐                                     │
│  [Mobile App 2] ──┼── HTTP + WS ─> [Coordinator:8002]  │
│  [Mobile App N] ──┘                         │            │
│                                              │            │
│                                              ├─> [Router:8003]
│                                              │     │      │
│                                              │     └─> [PostgreSQL]
│                                              │            │
│                                              ├─> [Traffic Manager:8004]
│                                              │     │      │
│                                              │     └─> [Redis Cache]
│                                              │            │
│                                              └─> [Data Processor:8005]
│                                                    │      │
│                                                    └─> [PostgreSQL]
│                                                          │
└──────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   SIMULATION MODE                        │
│                 (Testing & Demo)                         │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  [GUI Client] ──> [Coordinator:8002]                    │
│                         │                                │
│                         ├─> [Simulation:8001]           │
│                         │     (Virtual agents)          │
│                         │                                │
│                         ├─> [Router:8003]               │
│                         │     (K-shortest paths)        │
│                         │                                │
│                         ├─> [Traffic Manager:8004]      │
│                         │     (Synthetic congestion)    │
│                         │                                │
│                         └─> [Data Processor:8005]       │
│                               (OSM tiles, MVT)          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Microservices API

| Service | Port | Responsibility | Production | Simulation |
|---------|------|---------------|-----------|-----------|
| **Coordinator** | 8002 | Route orchestration, WebSocket hub | ✅ | ✅ |
| **Router** | 8003 | K-shortest paths (pgRouting) | ✅ | ✅ |
| **Simulation** | 8001 | Virtual agent physics engine | ❌ | ✅ |
| **Traffic Manager** | 8004 | Congestion tracking, Redis cache | ✅ | ✅ |
| **Data Processor** | 8005 | OSM downloads, MVT generation | ✅ | ✅ |

### Shared Libraries

```
src/
├── shared/              # Shared между микросервисами
│   ├── agent/          # AgentBatch, move_batch (Simulation)
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

## Что делать СЕЙЧАС (Phase 1)?

### 1. ✅ Удалить мёртвый код

```bash
# Удалить src/routing/ (полностью заменён на services/router)
git rm -r src/routing/

# Удалить тест старого routing
git rm tests/test_routing.py

# Commit
git add -A
git commit -m "Remove dead code: src/routing/ and legacy routing tests"
```

**Результат**: -800 строк, 0 функциональных изменений.

### 2. ✅ Создать ARCHITECTURE.md

Документ с финальной архитектурой:
- МАС концепция (реальный vs симуляция)
- Phase-by-phase план
- API спецификации
- Mermaid диаграммы

### 3. ✅ Создать Mermaid диаграммы

**Диаграмма 1**: Microservices interaction (Production)
**Диаграмма 2**: Microservices interaction (Simulation)
**Диаграмма 3**: Database schema (graphs, osm, tiles)
**Диаграмма 4**: Class diagram (key classes)

### 4. ⚠️ НЕ трогать legacy server

Причины:
- GUI зависит от него (100%)
- Нужна полная переработка в Phase 2-3
- Удаление сейчас сломает всё

## Выводы

### Ключевые решения:

1. **МАС = 2 режима**:
   - **Production**: агенты на клиентах (GPS), Simulation НЕ используется
   - **Testing**: агенты на сервере (Simulation), для отладки алгоритмов

2. **Агент НЕ зависит от симуляции** - верно!
   - Реальный агент = мобильное приложение с GPS
   - Виртуальный агент = сущность на сервере для тестирования
   - Симуляция = движок для виртуальных агентов

3. **Текущее состояние**:
   - Доделано: GUI, Data Processor, PostgreSQL, legacy server
   - Наброски: Router, Simulation, Coordinator, Traffic Manager
   - Мёртвый код: src/routing/ (дубль)

4. **Phase 1 (сейчас)**:
   - Удалить src/routing/ (-800 строк)
   - Создать ARCHITECTURE.md с планом
   - НЕ трогать legacy server (GUI зависит)

5. **Phase 2+ (будущее)**:
   - Доработать микросервисы до production
   - Мигрировать GUI на микросервисы
   - Удалить legacy server (-2120 строк)
   - Создать Mobile App для реального МАС

### Метрики:

- **Текущий код**: ~15000 строк
- **После Phase 1**: ~14200 строк (-800)
- **После Phase 4**: ~12200 строк (-2800)
- **Дублирование**: 0%
- **Микросервисы**: 5 (все production-ready после Phase 2)
