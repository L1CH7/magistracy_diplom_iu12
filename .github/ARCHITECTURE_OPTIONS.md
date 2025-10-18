# Architecture Options (3 Senior Proposals)

Date: 2025-10-18

This document captures three competing designs proposed by three senior engineers for the BMSTU MAS navigation project. Each proposal defines stack, architecture, functionality for R-D-1 (2-week MVP) and R-D-2 (intelligence), with scaling phases and trade-offs. A final recommendation concludes the document.

---

## Option A — WebGL-first desktop (PyQt + MapLibre GL JS) — “GPU smoothness, fast iteration”

- Client
  - UI: PyQt5/Qt6 + QWebEngineView
  - Map: MapLibre GL JS (WebGL) inside local HTML
  - IPC: QWebChannel or runJavaScript calls initially; migrate to WS in R-D-2
  - State: QSettings + client.yaml (persist last location, layer/style prefs)
  - Features (R-D-1):
    - Auto-center on last/estimated position; context menu on map: “Отсюда”, “Сюда”, “Добавить точку”
    - Multi-stop routing (N waypoints), reorder list, one-agent smooth animation
    - Configurable base tiles via TILE_URL; caching hooks
  - R-D-2:
    - WS subscription to agents stream; admin/dispatcher console view; filtering; flashing route changes
    - Draw advanced overlays (traffic heat, closures) as vector/raster layers

- Server
  - FastAPI (REST), later FastAPI WS
  - Routing: NetworkX in R-D-1 (prototype); pgRouting/Valhalla in R-D-2
  - Data: File JSON in R-D-1; PostGIS + Redis in R-D-2
  - Role: source of truth (agents, graph), coordinator (updates edge costs)

- Pros
  - Excellent GPU performance, smooth pan/zoom, web styling flexibility
  - Rapid iteration in Python; separation of UI (web) and logic (Python)
- Cons
  - Qt WebEngine needs correct system libs; Docker/X11/GPU setup can be finicky

- Suitability: Best balance of performance + dev speed. Matches current repo path.

---

## Option B — OpenLayers desktop (PyQt + OpenLayers) — “Rich edit toolbox, flexible projections”

- Client
  - PyQt + QWebEngineView, OpenLayers in HTML
  - Strong built-in drawing/modification tools (for future edits)
- Server
  - Same as Option A
- Pros
  - Powerful vector handling and feature editing
- Cons
  - Styling pipeline slightly heavier than MapLibre; performance comparable but MapLibre often simpler for vector tiles

- Suitability: Good if editing is core. For our path (no heavy editing now), A is simpler.

---

## Option C — Native Qt Location/QML — “All-native UI, fewer web deps”

- Client
  - Qt/QML + Qt Location/Positioning
- Server
  # Архитектурные опции (3 сеньора, подробная реализация и консенсус)

  Дата: 2025-10-18

  Этот документ фиксирует три конкурирующие архитектуры (A/B/C), обсуждение трёх сеньоров, детали реализации до уровня модулей/сервисов/API, а также итоговый гибридный консенсус для R-D-1 (2 недели) и R-D-2 (интеллект/масштабирование). Технологии подбираем прагматично: Python, PyQt, MapLibre/OpenLayers/Qt, FastAPI, PostGIS/pgRouting, Valhalla, Redis, WebSocket, Docker/Compose.

  ---

  ## Коротко о целевых фазах

  - R-D-1 (2 недели):
    - Десктоп-клиент с GPU-картой, плавной анимацией агента, мульти-остановочный маршрут, контекстное меню (Отсюда/Сюда/Добавить точку), автопозиционирование.
    - REST API на сервере; хранение графа в файлах (или временно в памяти).
    - Подготовлены хуки для TILE_URL, WS, PostGIS; Docker с X11/GPU для QtWebEngine.
  - R-D-2: 
    - Сервер — «истина» для агентов: WebSocket-стрим позиций/событий, обновление стоимости рёбер, реакция на пробки/закрытия.
    - Бэкенд на PostGIS + pgRouting или отдельный маршрутизатор (Valhalla). Redis для Pub/Sub/Streams/кэшей. Диспетчерская панель.

  ---

  ## Опция A — PyQt + QWebEngineView + MapLibre GL JS (WebGL)

  Сеньор «Алексей»: за WebGL-карту внутри PyQt. Быстрая разработка, плавный рендер, гибкое оформление.

  ### Клиент (реализация)

  - Стек: Python 3.11, PyQt5 (или Qt6 при готовности), PyQtWebEngine, MapLibre GL JS.
  - Структура клиента:
    - `src/client/gui.py`: главное окно, `QWebEngineView` загружает `assets/map.html`.
    - `src/client/assets/map.html`: слой base raster (или vector tiles), источники GeoJSON (graph, routes, agent), JS-API:
      - `setGraphGeoJSON(geojson)`, `setRoutes(geojson|array)`, `updateAgent({lon,lat,heading,speed})`, `fitToRoutes()`.
    - Связь Python→JS: `runJavaScript(...)` (R-D-1). R-D-2 — `QWebChannel` для обратной связи.
    - Состояние: `QSettings` + `client.yaml` (последний центр/масштаб, предпочитаемый TILE_URL, включённые слои).
  - Фичи (R-D-1):
    - Контекстное меню на карте (через JS listener + `qtbridge`): «Отсюда», «Сюда», «Добавить точку»; список остановок (Dock-панель) с drag&drop перестановкой; кнопка «Построить» вызывает REST.
    - Плавная анимация агента: JS `requestAnimationFrame`-интерполяция; частота обновления ~60 FPS; сервер отдаёт опорные точки/скорость.
    - Опционально кластеризация точек POI (если появятся).
  - Производительность:
    - WebGL аппаратно (QtWebEngine использует Chromium); в Docker — `/dev/dri`, переменные `QTWEBENGINE_DISABLE_SANDBOX=1`, системные библиотеки `libgl1`, `libxkbcommon-x11-0`, `libnss3`, `libasound2`.
    - При деградации — софтовый рендер и снижение частоты обновлений.

  ### Сервер (реализация)

  - Стек: FastAPI + Uvicorn. Схема REST:
    - `GET /graph` → GeoJSON рёбер/узлов (R-D-1 из файла или сгенерировано).
    - `POST /route` `{waypoints:[{lon,lat},...]}` → `FeatureCollection` LineString(ы) + метаданные (длина, ETA).
    - `GET /agents` → список агентов (R-D-2: WebSocket `/ws/agents`).
  - Хранение (R-D-1): в памяти/файлах (NetworkX для прототипа). R-D-2: PostGIS.
  - Маршрутизация:
    - R-D-1: упрощённая (Dijkstra/A* на NetworkX). 
    - R-D-2: pgRouting (pgr_dijkstra/pgr_astar) или Valhalla (внешний сервис), выбор зависит от покрытия/тюнинга.
  - События и кэш:
    - Redis (R-D-2):
      - Pub/Sub: канал `agents.pos.*` для широковещательных WS-апдейтов.
      - Streams: `routes:requests`/`routes:results` для задач offline/переобработки.
      - Кэш ключей стоимости рёбер и быстрых маршрутов (TTL), например `route:hash(waypoints)`.

  ### Данные (R-D-2)

  - PostGIS схема (минимум):
    - `road_nodes(id bigint primary key, geom geometry(Point, 4326))`
    - `road_edges(id bigint primary key, source bigint, target bigint, geom geometry(LineString, 4326), length_m double precision, speed_kmh double precision, base_cost double precision, tags jsonb)`
    - Топология: `pgr_createTopology('road_edges', 0.0001, 'geom', 'id')` создаёт `source/target` при импорте.
    - Индексы: GIST по `geom`, B-Tree по `source/target`.
    - pgRouting примеры:
      - `SELECT * FROM pgr_astar('SELECT id, source, target, base_cost AS cost, base_cost AS reverse_cost FROM road_edges', start, finish);`

  ### Плюсы/минусы (итого)

  - + Плавная карта, гибкий стиль через GL JSON, быстрые правки UI в HTML/JS.
  - + Лёгкая интеграция с PostGIS/Redis/WS.
  - – Требовательна к системным библиотекам QtWebEngine (особенно в Docker/X11/GPU).

  ---

  ## Опция B — PyQt + OpenLayers (веб-карта с сильным редактированием)

  Сеньор «Борис»: за OpenLayers — зрелые инструменты редактирования геометрии, проекции, богатый контроль векторных объектов.

  ### Клиент (реализация)

  - Стек: PyQt + QWebEngineView + OpenLayers 7.
  - HTML-страница `assets/map_ol.html` с:
    - Base layer (XYZ), vector sources для графа/маршрутов/агентов.
    - Инструменты `ol/interaction/Draw`, `Modify`, `Snap` (R-D-2 для админки/правок).
    - События карты/фич → отправка в PyQt через `QWebChannel`.
  - Маршруты и анимация:
    - Анимация — через `postrender` или таймеры OL; плавность сравнима, но GL-шейдеров нет (в отличие от MapLibre GL).

  ### Сервер

  - Аналогично Опции A. При редактировании — REST/WS эндпоинты для приёма геометрий изменений (геофичи → валидация → запись в PostGIS).

  ### Плюсы/минусы

  - + Сильные инструменты редактирования «из коробки», богатая геометрическая обработка на клиенте.
  - – Чуть тяжелее по коду для анимаций и производительности с большими наборами фич (без WebGL-ускорения).

  ---

  ## Опция C — Qt/QML + Qt Location (натив)

  Сеньор «Кира»: за полностью нативный стек (QML), плотная интеграция, минимум веб-зависимостей.

  ### Клиент (реализация)

  - Стек: Qt 6 + QML (Qt Quick), модуль Qt Location/Positioning.
  - Рендер карты и слоёв нативно, маркеры/оверлеи — QML компоненты.
  - Взаимодействие с Python через PySide6/PyQt6 (или C++ backend при необходимости максимума производительности).

  ### Сервер

  - Тот же (FastAPI/PostGIS/Redis), протоколы те же.

  ### Плюсы/минусы

  - + Нативная интеграция, предсказуемая упаковка под десктопы.
  - – Беднее экосистема карт/стилей, выше порог для сложной веб-стилизации, больше усилий на собственные инструменты.

  ---

  ## Спор сеньоров (краткий стенограммный формат)

  - Алексей (A): «Нужна плавность и скорость. MapLibre GL — идеально для визуального UX и будущих векторных тайлов. Редактирование не в приоритете R-D-1; дотянем до R-D-2 через простые Tools или отдельную админку.»
  - Борис (B): «Редактирование всё равно придёт (закрытия дорог, ручные правки). OpenLayers даст нам это быстрее и аккуратнее. Плюс проекции и геометрические операции удобнее.»
  - Кира (C): «Натив — меньше зависимостей, лучше контроль GUI. В контейнере Chromium/QtWebEngine — боль (libGL, X11). QML стабильнее для стендовой машины.»

  Контраргументы:
  - А: «Редактирование можно вынести в отдельный админ-инструмент (OpenLayers), а основную клиентскую часть оставить на MapLibre для производительности.»
  - B: «Тогда придётся поддерживать две HTML-страницы и два набора JS-утилит.»
  - C: «И в любом случае у нас PostGIS и WS; выбор клиента можно развязать: диспетчер — в вебе/OL, исполнитель — в PyQt/WebGL.»

  Решения по фактам/рискам:
  - Docker/X11/GPU: да, QtWebEngine требует системные библиотеки. Но это решаемо (libgl1, libxkbcommon-x11-0, libnss3, libasound2, /dev/dri). Проверено на dev-машинах.
  - Производительность: MapLibre GL стабильно даёт плавность при больших линиях/маркерах. OL — ок, но GL-эффектов меньше.
  - Time-to-Feature: R-D-1 важнее скорость UX; редактирование — не критично.

  Итог спора: делаем гибрид.

  ---

  ## Консенсус (гибрид): A как основной клиент + B как админ-редактор; C — резерв для стойки/встраивания

  1) Основной клиент (исполнитель): PyQt + QWebEngineView + MapLibre GL (Опция A).
     - R-D-1: реализуем полностью (см. критерии ниже).
     - R-D-2: добавляем WS, PostGIS/pgRouting/Valhalla, Redis Pub/Sub для трансляции позиций.

  2) Админ/диспетчер/редактор: отдельная HTML-страница c OpenLayers (Опция B) в том же клиенте (вторая вкладка) или как отдельный «режим»/вью.
     - Инструменты редактирования (closures, speed limits, one-way changes) → REST/WS на сервер, запись в PostGIS.
     - Модерация/откат через версионирование геоизменений (отдельная таблица audit_changes).

  3) Опция C (QML) — пока не делаем, но держим как fallback для киосков/встраиваемых устройств.

  ---

  ## Интеграционный дизайн (детали до реализации)

  ### Docker/Compose (набросок служб)

  - `server`: FastAPI + Uvicorn.
  - `client`: Python + PyQt + QtWebEngine (X11 forward, /dev/dri).
  - `db`: PostGIS (postgis/postgis:15-3.3).
  - `redis`: Redis 7 (в т.ч. Streams).
  - `tiles` (опционально позже): tegola/tileserver-gl/t-rex для MVT; пока используем внешние XYZ.

  Переменные окружения (ключевые):
  - `TILE_URL` (например, https://tile.openstreetmap.org/{z}/{x}/{y}.png)
  - `QTWEBENGINE_DISABLE_SANDBOX=1`
  - `DISPLAY`, volume: `/tmp/.X11-unix`, devices: `/dev/dri`.

  ### Протоколы и API

  - REST (R-D-1):
    - `POST /route` → `{ waypoints: [{lon,lat}, ...], profile?: 'car'|'emergency' }` → `FeatureCollection` + `{distance_m, duration_s}`.
    - `GET /graph` → упрощённый GeoJSON.
  - WS (R-D-2):
    - Topic `agents`: `{id, lon, lat, heading, speed, ts}` (10–20 Гц для локальной демо; 1–5 Гц для реальных масштабов).
    - Topic `events`: дорожные события/закрытия.
  - Redis:
    - Pub/Sub `ws:agents`, `ws:events` — бэкенд пушит, WS-шлюз транслирует клиентам.
    - Streams `routing:requests`, `routing:results` — фоновые рассчёты/очереди.
    - Кэш `route:*` (TTL) и `edge_cost:*` для динамики.

  ### PostGIS детали

  - Таблицы (минимум): `road_nodes`, `road_edges` (см. выше), `closures` (edge_id, from_ts, to_ts, metadata), `speed_overrides` (edge_id, value, priority), `audit_changes` (jsonb, author, ts).
  - Триггеры/матвью: пересчёт `base_cost`/`current_cost` при изменениях.
  - Индексы: GIST/BRIN для длинных линий; `btree (edge_id)` на изменениях.

  ### Маршрутизация

  - Вариант 1 (pgRouting): быстро встраивается в PostGIS, но требует корректной топологии и тюнинга.
  - Вариант 2 (Valhalla): отдельный сервис, гибкие профили, качественные ETA/манёвры; потребует импорта OSM/tiles.
  - R-D-2 план: начинаем с pgRouting; если нужны профили/манёвры — включаем Valhalla параллельно и сравниваем.

  ### Клиентская архитектура (PyQt + MapLibre)

  - Модули:
    - `MapBridge` (Qt QObject) ↔ JS: буферизация вызовов до `loadFinished`.
    - `RouteModel`: точки, порядок, профили, вызов REST, хранение последнего результата.
    - `AgentAnimator`: таймер PyQt для обновления модели скорости/позиции; JS — отрисовка.
    - `SettingsService`: QSettings + YAML.
    - (R-D-2) `WsClient`: подписка на WS, обновление слоёв (агенты, события).
  - Слои карты:
    - base raster/vector, `graph` (тонкие линии), `routes` (активный/альтернативы), `agent` (иконка + heading), `overlays` (closures, traffic heat).

  ### Админ-редактор (OpenLayers)

  - Режим в том же приложении (вторая вкладка) или отдельный профайл запуска.
  - Интеракции: Draw/Modify/Snap. Экспорт правок → GeoJSON → POST `/admin/changes` → PostGIS.
  - Валидация: серверная (пересечение с существующими, корректность направлений, топология).

  ### Набор нефункциональных требований

  - FPS: 50–60 при одиночном агенте и активном маршруте.
  - Обновления позиции: 10 Гц локально; падение частоты gracefully.
  - Время ответа `POST /route`: R-D-1 ≤ 300 мс на короткие, ≤ 1.5 с на длинные (в памяти). R-D-2 с PostGIS/pgRouting — цель ≤ 500–800 мс.

  ### Тестирование

  - Unit: маршрутизация (короткие графы), преобразование координат, сериализация GeoJSON.
  - Интеграция: REST/WS контрактные тесты; Redis pub/sub loopback; PostGIS pgr_* smoke.
  - UI: QtTest сценарии (контекстное меню, добавление точек); «скриншотные» тесты основных видов.

  ### Безопасность и эксплуатация

  - Включить флаги QtWebEngine sandbox (при возможности) или документировать риск.
  - Логи: JSON (эндпоинты, время, размеры ответов), метрики (Prometheus) — R-D-2.

  ---

  ## Критерии готовности

  ### R-D-1 (за 2 недели)

  - Клиент:
    - GPU карта (MapLibre) в окне PyQt, плавное масштабирование/перетаскивание, дороги видны до маршрутов.
    - Контекстное меню Отсюда/Сюда/Добавить точку; список остановок с reorder; кнопка Построить.
    - Плавная анимация одного агента по текущему маршруту; автоподгон карты (fit bounds).
    - Настройки сохраняются (центр, зум, TILE_URL).
  - Сервер:
    - `GET /graph`, `POST /route` (в памяти/NetworkX), корректный GeoJSON.
    - Докер-композ с клиентом (X11/GPU), сервером; TILE_URL как env.

  ### R-D-2

  - WS-стрим агентов и событий; Redis Pub/Sub как шина; сервер — «истина» для позиций.
  - PostGIS + pgRouting (или Valhalla): маршруты с учётом закрытий/переопределений скоростей, SLA по времени.
  - Админ-редактор (OpenLayers) для правок сети и событий; аудит изменений.

  ---

  ## Итог: принимаем гибрид

  - База: Опция A (PyQt + MapLibre). Достаём UX-цели быстро и с максимальной плавностью.
  - Редактирование/админ: Опция B (OpenLayers) как отдельный режим/вкладка R-D-2.
  - Redis — для Pub/Sub (WS широковещание), Streams (очереди задач), кэш роутов/стоимостей.
  - PostGIS/pgRouting — как первый промышленные маршрутизатор; Valhalla — как опция для профилей/манёвров.

  Следующие шаги:
  - Завершить клиентский Docker образ: добавить системные либы QtWebEngine (libgl1, libxkbcommon-x11-0, libnss3, libasound2), убедиться в X11/GPU рендере.
  - В `docker-compose.yml` — /dev/dri, X11, TILE_URL, флаги QtWebEngine.
  - Подготовить PostGIS/Redis как «неактивные» сервисы (scaffold) и простую миграцию данных (импорт из GeoJSON/OSM).
