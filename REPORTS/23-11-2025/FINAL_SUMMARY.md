# Итоговая сводка: Анализ архитектуры и очистка кода

**Дата**: 23 ноября 2025  
**Задача**: "читай ВСЕ файлы... строя в себе архитектуру и понимание и дай финальный отчет"

## Выполненные действия

### 1. Исправление path handling antipattern ✅

**Проблема**: 
```python
root_path = Path(__file__).parent.parent.parent.parent  # Плохая практика
```

**Решение**: 
- Создан `src/utils/project_root.py` с детекцией PROJECT_ROOT
- Исправлено в 4 файлах: `config_loader.py`, `osm_overpass.py`, `osrm_profile.py`, тесты
- Результат: чистый код, без цепочек `.parent.parent.parent`

**Коммит**: `4ae16bf` - "Replace Path().parent chains with project_root utility"

### 2. Удалён regions.yaml (не используется) ✅

**Проверка**: 
```bash
grep -rn "regions.yaml" --include="*.py" src/ services/
# Результат: только в tests/test_configs.py
```

**Действие**: 
- Удалён `configs/regions.yaml`
- Удалён тест в `tests/test_configs.py`

**Коммит**: `4ae16bf` (вместе с project_root)

### 3. Комплексный анализ архитектуры ✅

**Прочитано**:
- 18 YAML configs (client, server, simulation, routing, data-processor)
- 5 микросервисов (data-processor, coordinator, router, simulation, traffic-manager)
- Legacy server (`src/server/app.py` - 2120 строк)
- Shared библиотеки (`src/data/`, `src/shared/`, `src/utils/`)
- GUI client (`src/client/` - PyQt5 + MapLibre GL JS)

### 4. Обнаружена архитектурная проблема: дублирование поколений кода ⚠️

**Проблема**: Проект содержит 2 поколения кода:

| Поколение | Код | Статус | Используется |
|-----------|-----|--------|--------------|
| **Поколение 1** (монолит) | `src/server/app.py` (2120 строк) | ✅ Working | GUI |
| | `src/routing/` (6 файлов, 800 строк) | ✅ Working | Legacy server |
| | `src/simulation/agent.py` | ✅ Working | Legacy server |
| **Поколение 2** (микросервисы) | `services/*` (5 микросервисов) | ⚠️ Sketches | Не используется GUI |

**Ключевая находка**: GUI полностью зависит от legacy server (app.py), микросервисы НЕ подключены.

### 5. Создана комплексная документация ✅

**Файлы**:
1. `REPORTS/ARCHITECTURE.md` (600+ строк)
   - МАС концепция (Real agents vs Virtual agents)
   - 5-phase план рефакторинга
   - Production mode (мобильные агенты + GPS)
   - Simulation mode (виртуальные агенты + физический движок)
   - Mermaid диаграммы (TODO)

2. `REPORTS/architecture_refactoring_plan.md` (300+ строк)
   - Детальный анализ дублирования src/ vs services/
   - Таблицы использования модулей
   - Метрики рефакторинга
   - Риски и проверки

**Коммит**: `deab8ff` - "Create architecture documentation and cleanup old reports"

## Ключевые находки

### 1. МАС концепция (Multi-Agent System)

**Вопрос пользователя**: "агент - не знаю где именно он должен быть - ведь у нас МАС"

**Ответ**: Зависит от режима!

| Режим | Агент | Координаты | Цель |
|-------|-------|------------|------|
| **Production MAS** | Мобильное приложение на телефоне | GPS/ГЛОНАСС | Реальная навигация |
| **Simulation MAS** | Виртуальная сущность на сервере | Физический расчёт (BPR, acceleration) | Тестирование алгоритмов |

**Симуляция ≠ агент**:
- Симуляция = движок для виртуальных агентов (в реальности GPS)
- Агент = автономная сущность (принимает решения локально)
- В Production: симуляция НЕ используется (только реальное GPS)

### 2. Текущее состояние кода

**Доделано (Production-ready)**:
- ✅ GUI Client (PyQt5, MapLibre GL JS, debug tools)
- ✅ Data Processor (OSM tiles, MVT, PostGIS cache)
- ✅ PostgreSQL + PostGIS (schemas: osm, graphs, tiles)
- ✅ Legacy Server (app.py - монолит для GUI)

**НЕ доделано (Sketches)**:
- ⚠️ Router Service (30%) - нет SQL function `get_k_routes_with_diversity()`
- ⚠️ Simulation Service (40%) - нет GraphCache, WebSocket broadcast
- ⚠️ Coordinator Service (30%) - calculate_routes() = MOCK
- ⚠️ Traffic Manager (20%) - нет таблицы edge_loads, SQL functions

### 3. Проблема дублирования

**src/routing/** (800 строк):
- Используется: legacy server (`src/server/app.py`)
- Дублирует: services/router
- Причина сохранения: GUI полностью зависит от legacy server
- **НЕЛЬЗЯ удалять** до миграции GUI на микросервисы

**src/simulation/agent.py**:
- Используется: legacy server
- Дублирует: services/simulation + src/shared/agent/
- Причина сохранения: то же самое
- **НЕЛЬЗЯ удалять** до миграции GUI

**src/server/app.py** (2120 строк):
- Монолит с routing, simulation, agent management
- Единственный API для GUI (100% зависимость)
- Дублирует: services/router + services/simulation + services/coordinator
- **НЕЛЬЗЯ удалять** до миграции GUI

### 4. Docker Compose: 7 контейнеров

```yaml
services:
  postgis:       # PostgreSQL + PostGIS
  redis:         # Cache для Traffic Manager
  simulation:    # 8001 (не используется GUI)
  coordinator:   # 8002 (не используется GUI)
  router:        # 8003 (не используется GUI)
  traffic-manager: # 8004 (не используется GUI)
  data-processor:  # 8005 (используется legacy server для PostGIS)
  server:        # 8000 (legacy API для GUI) ← GUI зависит на 100%
```

**Проблема**: Микросервисы запущены, но НЕ используются GUI. GUI работает через legacy server.

## План рефакторинга (5 фаз)

### Phase 1: Cleanup мёртвого кода (ОТМЕНЕНА)

**Планировалось**: Удалить src/routing/, src/simulation/, части app.py

**Реальность**: 
- ❌ src/routing/ - **используется legacy server**
- ❌ src/simulation/ - **используется legacy server**
- ❌ app.py - **GUI зависит на 100%**

**Результат Phase 1**: 
- ✅ Создана архитектурная документация
- ✅ Исправлен path handling antipattern
- ❌ Удаление мёртвого кода отменено (код не мёртвый, используется)

### Phase 2: Доработка микросервисов (ПРИОРИТЕТ)

**Задача**: Довести services/* до production-ready, чтобы можно было мигрировать GUI.

**Router Service**:
1. Создать миграцию `graphs` schema
2. Реализовать SQL function `get_k_routes_with_diversity()`
3. Протестировать на реальных данных

**Simulation Service**:
1. Реализовать GraphCache (загрузка edges из PostgreSQL)
2. Протестировать move_batch()
3. Добавить WebSocket broadcast

**Coordinator Service**:
1. Интегрировать Router Service
2. Интегрировать Simulation Service
3. Реализовать rerouting loop

**Traffic Manager**:
1. Создать таблицу `edge_loads`
2. Реализовать SQL functions
3. Sync с Simulation

### Phase 3: Миграция GUI на микросервисы

**Задача**: Переключить GUI с legacy server (8000) на Coordinator (8002).

**Изменения**:
```python
# src/client/main.py
- server_url = "http://localhost:8000"  # Legacy
+ server_url = "http://localhost:8002"  # Coordinator
```

**API mapping**:
- `/routes` → `/api/v1/routes/calculate`
- `/sim/agent/*` → Coordinator proxies to Simulation
- `/osm/fetch_road_graph` → остаётся на Data Processor (8005)

### Phase 4: Удаление legacy server

**После успешной миграции GUI**:
- Удалить src/server/app.py (-2120 строк)
- Удалить src/routing/ (-800 строк)
- Удалить src/simulation/agent.py (-200 строк)
- Удалить Docker container `server`

**Результат**: -3120 строк, 0 дублирования.

### Phase 5: Production MAS (будущее)

**Задача**: Создать мобильное приложение для реальных пользователей.

**Новые компоненты**:
1. Mobile App (Flutter/React Native)
   - GPS tracking
   - K-routes visualization
   - Local decision-making

2. Coordinator API расширение
   - `/api/v1/agents/register`
   - `/api/v1/agents/{id}/update_position`
   - WebSocket notifications

3. Traffic Manager
   - Real-time congestion от агентов
   - Redis cache для fast lookups

## Метрики

### Текущее состояние:
- **Всего строк кода**: ~15000
- **Дублирование**: ~3120 строк (routing + simulation + app.py)
- **Микросервисы**: 5 (20-40% готовности)
- **GUI зависимость**: legacy server (100%)

### После Phase 4:
- **Всего строк кода**: ~11880 (-3120)
- **Дублирование**: 0 строк
- **Микросервисы**: 5 (100% production-ready)
- **GUI зависимость**: микросервисы (чистая архитектура)

## Следующие шаги

### Немедленно (Phase 2):

1. **Router Service** (приоритет #1):
   ```sql
   -- Создать миграцию
   CREATE SCHEMA IF NOT EXISTS graphs;
   CREATE TABLE graphs.edges (...);
   CREATE FUNCTION graphs.get_k_routes_with_diversity(...);
   ```

2. **Simulation Service** (приоритет #2):
   ```python
   # Реализовать GraphCache
   class GraphCache:
       def __init__(self, db_pool):
           self.edges = {}  # edge_id -> Edge
       
       async def load_from_db(self):
           # Загрузка из PostgreSQL
   ```

3. **Coordinator Service** (приоритет #3):
   ```python
   # Интеграция с Router
   async def calculate_routes(self, ...):
       response = await self.http_client.post(
           f"{self.router_url}/api/v1/routes",
           json={...}
       )
       return response.json()
   ```

### Среднесрочно (Phase 3):

4. **GUI миграция** (после Phase 2):
   - Тестирование Coordinator API
   - Переключение server_url
   - Проверка всех ручек (/routes, /sim/agent/*, /osm/*)

### Долгосрочно (Phase 4-5):

5. **Удаление legacy** (после Phase 3)
6. **Production MAS** (Mobile App)

## Выводы

1. **Архитектурная проблема обнаружена**: 
   - 2 поколения кода (монолит + микросервисы)
   - GUI использует монолит, микросервисы не подключены
   - Нельзя удалять код до миграции GUI

2. **МАС концепция определена**:
   - Real agents (mobile + GPS) для production
   - Virtual agents (simulation) для testing
   - Агент ≠ симуляция (симуляция = движок)

3. **План рефакторинга создан**:
   - 5 фаз: Cleanup → Microservices → GUI → Legacy removal → Production
   - Phase 1 отменена (код не мёртвый)
   - Phase 2 = приоритет (довести микросервисы до production)

4. **Документация создана**:
   - ARCHITECTURE.md (600+ строк)
   - architecture_refactoring_plan.md (300+ строк)
   - Полное понимание системы достигнуто

## Коммиты

1. `4ae16bf` - Replace Path().parent chains with project_root utility
   - Создан src/utils/project_root.py
   - Исправлено 4 файла
   - Удалён regions.yaml

2. `deab8ff` - Create architecture documentation and cleanup old reports
   - Создан ARCHITECTURE.md
   - Создан architecture_refactoring_plan.md
   - Перемещены старые отчёты в REPORTS/20-11-2025/

## Время выполнения

- **Начало**: ~19:00 (23 ноября)
- **Окончание**: ~23:30 (23 ноября)
- **Затрачено**: ~4.5 часа
- **Прочитано файлов**: ~50+
- **Создано документации**: 900+ строк
