MD-ФАЙЛ ДЛЯ АГЕНТА

Название: ARCHITECTURE_PLAN.md

Содержимое:

# MAS Navigation System — Архитектурный план и задания

Цели

- Построить модульную систему, где:
    - Граф и визуализация — PostGIS;
    - Маршрутизация — через абстракцию RoutingProvider (дефолт: pgRouting);
    - Симуляция и MAS тесно связаны с графом (current_load → effective_speed);
    - Легкая замена маршрутизатора (pgRouting ⇄ A* ⇄ др.);
    - Масштабирование от 1 агента/клиента до 1000+ агентов и координатора.

Сервисы и сущности

- PostGIS (с pgRouting):
    - Хранит граф (nodes, edges), атрибуты OSM, динамику (current_load, effective_speed), метрики.
    - Выполняет pgr_* функции (Dijkstra, kSP, snap).
- API Server (FastAPI):
    - Orchestrator: предоставляет REST/WebSocket для клиента/админки.
    - Инкапсулирует RoutingProvider (PgRoutingProvider по умолчанию).
    - Предоставляет Graph API (bbox → GeoJSON) для клиента.
    - Экспортирует метрики (Prom/Grafana), логирует в Loki.
- Simulation Worker:
    - Дискретная симуляция (шаг t=1s, конфигурируемо).
    - Обновляет current_load/counters в edges (батчами).
    - По расписанию дергает RoutingProvider для пересчета маршрутов (если включен MAS).
- Coordinator (MAS):
    - Анализирует congestion/метрики, принимает решения о распределении.
    - Вызывает RoutingProvider (K альтернатив) и назначает маршруты агентам.
    - В R\&D-1 — stub/off; в R\&D-2 — включается.
- Client GUI (PyQt5 + MapLibre):
    - Отрисовывает тайлы, граф (из API → PostGIS), маршруты и агентов.
    - Управляет одним агентом (в R\&D-1) и получает K маршрутов.
- Admin GUI (в R\&D-2):
    - Мониторинг 1000+ агентов, heatmap загрузки, управление сценариями.

Дерево модулей (предлагаемая структура репозитория)

- services/
    - api/
        - main.py               \# FastAPI
        - deps.py               \# DI контейнер, конфиги
        - routers/
            - graph.py            \# /graph/bbox, /graph/snap
            - routing.py          \# /routing/route, /routing/k_routes
            - agents.py           \# /agents CRUD, /agents/positions
            - simulation.py       \# /sim/start, /sim/stop, /sim/state
            - metrics.py          \# /metrics (Prometheus)
        - domain/
            - models.py           \# DTO/схемы: Edge, Node, Route, Agent
            - interfaces.py       \# RoutingProvider, GraphProvider
            - routing_providers/
                - pgrouting.py      \# PgRoutingProvider (основной)
                - astar.py          \# AStarProvider (fallback)
                - valhalla.py       \# Placeholder (не активен)
            - graph_provider/
                - postgis.py        \# чтение графа по bbox из PostGIS
        - infra/
            - db.py               \# соединение с Postgres/PostGIS
            - cache.py            \# Redis optional (bbox cache)
            - logging.py          \# Loki/structlog
            - config.py           \# считывание YAML конфигов
    - simulation/
        - loop.py               \# дискретная симуляция (шаги)
        - updater.py            \# батч-обновления current_load/effective_speed
        - coordinator.py        \# MAS-логика (в R\&D-2)
        - cost_functions.py     \# формулы скорости/стоимости (из config)
        - adapters/
            - db_adapter.py       \# паблик API к БД из симуляции
            - routing_adapter.py  \# вызывает RoutingProvider (HTTP к API или прямой вызов)
    - client/                 \# PyQt5 + MapLibre (без изменений архитектурно)
        - ...
    - admin/                  \# R\&D-2
        - ...
- db/
    - schema.sql              \# таблицы и индексы
    - functions.sql           \# SQL функции (стоимость, snap wrappers)
    - seeds.sql               \# тестовые данные
    - migrations/             \# миграции, если используем Alembic
- ops/
    - docker-compose.yml      \# postgis(pgrouting), api, simulation, grafana, loki
    - grafana/                \# dashboards
    - loki/                   \# config
    - env/                    \# .env.example

Контракты (интерфейсы)

- RoutingProvider (domain/interfaces.py):
    - route(points: list[Point], k: int = 1, profile: str = "car") -> list[Route]
        - points: через waypoints [A, via1, via2, B]
        - если k>1: вернуть K альтернатив целого пути (R\&D-1), позже поддержка K по каждому leg.
    - snap(point: Point, radius: float = 50) -> SnappedPoint
    - health() -> bool
- GraphProvider:
    - get_edges_bbox(bbox: BBox, filters: dict) -> GeoJSONFeatureCollection
    - get_nodes_bbox(bbox: BBox) -> GeoJSONFeatureCollection

Реализация PgRoutingProvider

- Для via-точек: разбить маршрут на пары (A→via1, via1→via2, via2→B), вызвать pgr_dijkstra/pgr_ksp для каждой пары, слить.
- Для K альтернатив всего пути (R\&D-1): можно начать с K для основной пары A→B (если без via), либо строить K по первому leg и комбинировать (простая декомпозиция).
- Snap: pgr_findClosest или ST_ClosestPoint + ближайшее ребро с фильтрами.

SQL (db/schema.sql — основные таблицы)

- nodes(id bigint pk, geom geometry(Point, 4326))
- edges(
id bigint pk,
source bigint,            -- node_id
target bigint,            -- node_id
geom geometry(LineString, 4326),
length_m double precision,
highway text,
lanes int,
maxspeed_kmh int,
oneway boolean,
capacity int,             -- (length/5)*lanes (настраиваемо)
current_load int default 0,
effective_speed_kmh double precision,  -- обновляется симуляцией
cost double precision                  -- materialized cache (опционально)
)
- agents(
id uuid pk,
state text,               -- idle/moving/finished
current_edge bigint null,
position_frac double precision default 0,  -- 0..1
speed_kmh double precision,
route_id uuid null
)
- routes(
id uuid pk,
created_at timestamptz,
k_index int,              -- порядковый номер альтернативы
total_cost double precision,
total_time_sec double precision
)
- route_edges(route_id uuid, seq int, edge_id bigint, primary key(route_id, seq))

Индексы

- GIST на edges.geom
- btree на edges(source), edges(target)
- partial index на edges(current_load) при необходимости

Формулы (simulation/cost_functions.py)

- capacity = max(1, floor(length_m / vehicle_length_m) * lanes)
- congestion = current_load / capacity
- effective_speed_kmh = max(
min_speed_kmh,
maxspeed_kmh * (1 - alpha * congestion^beta)
)
- cost_sec = length_m / (effective_speed_kmh / 3.6) + turn_penalties
- все коэффициенты (vehicle_length_m, alpha, beta, min_speed_kmh) — из config.yml

API (минимально необходимое)

- GET /graph/bbox?bbox=…\&filters=… → GeoJSON дорог (из PostGIS)
- POST /routing/route
    - body: { points: [{lat, lon, type}], k: 3 }
    - returns: [{ route_id, geojson, total_time_sec, legs: [...] }, ...]
- POST /graph/snap
    - body: { lat, lon, radius }
    - returns: { lat_snapped, lon_snapped, edge_id }
- POST /sim/start | /sim/stop | /sim/state
- WS /stream/agents — позиции агентов для клиента (каждую секунду)

Симуляция (services/simulation/loop.py)

- Шаг dt=1s:

1) Считать позиции агентов (из памяти/БД).
2) Сбросить edge load counters в памяти, посчитать current_load per edge из агентских состояний (в памяти) и разом записать в БД (batch update) каждые N секунд (например, 1–5 сек).
3) Пересчитать effective_speed_kmh по формуле (в памяти или одной SQL-функцией обновления, предпочтительно: батчевый UPDATE с выражением).
4) Обновить положение агентов вдоль текущего edge (position_frac += v*dt/length).
        - если position_frac >= 1: перейти на следующий edge (уведомить load-карты на следующем батче).
5) Каждые T секунд (например 30) — дергать Coordinator для пере-назначения маршрутов части агентов (в R\&D-1 выключено).
6) Отправить позиции/метрики через WS клиентам.

Coordinator (services/simulation/coordinator.py)

- R\&D-1: заглушка.
- R\&D-2: анализирует max load, группирует агентов по OD-парам, получает K альтернатив у RoutingProvider, распределяет с учетом глобального критерия (min max congestion или min total time).

Производительность и масштабирование

- pgRouting:
    - Ограничивать запросы по bbox/компоненту (не по всей карте).
    - Поддерживать precomputed connected component id для узлов/ребер; перед pgr_* фильтровать по компоненте старта/финиша.
    - Индексы обязательны (см. выше).
- Батч обновления БД: не писать по одному агенту; собирайте изменения в памяти и разом применяйте UPDATE edges SET current_load = … для множества id.
- Роутинг для 1000 агентов:
    - Параллелизм на уровне процессов (ProcessPool) или воркеров; ограничить запросы к БД пулом соединений.
    - Частоту пере-маршрутизации держать 20–60 сек; для движущихся агентов — локальный план на 1–2 ребра вперед.

Наблюдаемость

- Логирование в Loki (структурированное).
- Метрики:
    - routing_time_ms (гистограмма)
    - sim_step_ms
    - agents_active
    - edge_max_congestion
    - avg_travel_time_sec (baseline vs MAS)
- Дашборды Grafana.

Конфигурация (ops/env/.env, services/api/infra/config.py)

- Формулы скорости/стоимости (коэффициенты) — в config.yml
- Провайдер маршрутизации: routing.provider = pgrouting|astar|…
- Параметры pgRouting: k_max, directed, penalties
- Частоты симуляции: dt, batch_update_interval, reroute_interval

План работ (R\&D-1 → R\&D-2)

Этап 1 (R\&D-1, сейчас)

- [ ] Перестроить проект по структуре (services/{api,simulation}, domain/interfaces).
- [ ] Добавить pgRouting в Postgres, написать schema.sql, индексы.
- [ ] Реализовать PgRoutingProvider: route (via-точки), k_routes, snap.
- [ ] GraphProvider из PostGIS: bbox → GeoJSON (+ фильтры по OSM-тегам).
- [ ] Минимальный Simulation Worker: один агент, движение по маршруту, без MAS.
- [ ] API эндпоинты и интеграция с клиентом: показывать K маршрутов, активный — зеленым; агент движется по активному.
- [ ] Конфиги формул (effective_speed) и весов.

Этап 2 (R\&D-2)

- [ ] Многократные агенты (100–1000), батч-обновления load и скоростей.
- [ ] Coordinator (MAS): простая стратегия распределения (K альтернатив).
- [ ] Admin GUI: heatmap загруженности, мониторинг агентов.
- [ ] Отчет и эксперименты: baseline (все по кратчайшему) vs MAS (распределение).

Требования к качеству/проверки

- Согласованность графа: один PBF → PostGIS; не смешивать источники.
- Точность снапа: использовать PostGIS snap, чтобы точки на карте и маршруты совпадали.
- Сравнение маршрутов: 10–20 тестовых OD пар — pgRouting vs OSRM (без пробок) для sanity check.
- Производительность: pgr_dijkstra/pgr_ksp < 200ms на типичных дистанциях в городской черте; 1000 маршрутов параллельно < 10–20 сек (с пулом).

Заметки по замене провайдера

- Все контроллеры API вызывают только интерфейс RoutingProvider.
- Провайдер выбирается в конфиге (env или yaml).
- AStarProvider использует тот же граф из БД (извлекает edges в память либо исп. server-side вычисления).

Риски и их закрытие

- pgr_ksp может быть тяжелым: ограничивать область поиска (bbox/компонента), уменьшать k, добавлять diversity penalty на уровне координатора.
- Частые перезапросы маршрутов перегружают БД: вводить гистерезис (не пересчитывать тем, кто далеко от развилок), кэшировать короткое время.
- Состояние агентов в БД: держать оперативное состояние в памяти воркера, в БД писать снапшот/батчи.

Критерии готовности R\&D-1

- GUI: точки, K маршрутов, выбор активного, движение одного агента.
- API: /graph/bbox, /routing/route (via), /routing/k_routes, /graph/snap, /sim/*.
- БД: edges с динамическими полями (current_load, effective_speed), индексы.
- PgRoutingProvider: корректный маршрут для via-точек; K альтернатив (базово).
- Документация: config формул, инструкция запуска (docker-compose), список метрик.

Конец файла.
