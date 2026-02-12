# Технический отчет: Модуль обработки геоданных (Data Processor)

## Аннотация

Данный отчет описывает проектирование, реализацию и отладку модуля обработки геоданных для системы навигации Московской агломерации. Система построена на базе PostgreSQL + PostGIS и обеспечивает загрузку данных OpenStreetMap через Overpass API, генерацию векторных тайлов (MVT) в реальном времени и динамическую настройку уровней детализации (LOD). Ключевые достижения: устранение критических ошибок рендеринга на высоких зумах (Z14+), реализация мягких границ загрузки (Soft BBox Check), оптимизация структуры MVT для совместимости с MapLibre GL.

**Ключевые компромиссы:** Генерация тайлов «на лету» вместо предварительного кеширования — обмен дискового пространства на гибкость конфигурации. Отказ от растровых тайлов в пользу векторных — обмен простоты на масштабируемость стилизации.

---

## Структура отчета

### [Глава 1: Архитектура и выбор технологий](./01_architecture.md)

**Содержание:**
- Анализ альтернатив (Tileset API, Tileserver GL, Tegola).
- Обоснование выбора PostgreSQL + PostGIS + ST_AsMVT.
- Архитектура On-Demand Generation.
- Разделение ответственности (Handlers, API, Database).

**Ключевые выводы:**
- Отказ от предварительного кеширования ради динамической LOD.
- Выбор asyncpg для параллельной генерации тайлов.
- Компромисс: генерация «на лету» медленнее статических тайлов, но гибче.

---

### [Глава 2: Загрузка данных OpenStreetMap](./02_data_loading.md)

**Содержание:**
- Интеграция с Overpass API (плиточная нарезка, rate limiting).
- Проблема дублирования данных (решение: ON CONFLICT).
- Статистика загрузки (размер тайлов, количество объектов).
- Контроль качества: валидация геометрии, восстановление атрибутов.

**Ключевые метрики:**
- Размер тайла: 0.05° × 0.05° (~5.5 км × 3.7 км на широте Москвы).
- Средний размер ответа Overpass: ~1.2 МБ (JSON).
- Время загрузки одного тайла: 3–8 секунд (зависит от плотности дорог).
- Конкурентность: 5 параллельных запросов (ограничение Overpass).

---

### [Глава 3: Генерация MVT-тайлов](./03_mvt_generation.md)

**Содержание:**
- Формат Mapbox Vector Tiles (спецификация, Protocol Buffers).
- SQL-запрос GENERATE_MVT_TILE (ST_AsMVTGeom, буферизация, фильтрация).
- Динамическая LOD: синхронизация с клиентом через WebSocket.
- Проблема вложенных атрибутов (решение: плоская структура).
- Z-order: сортировка дорог по приоритету (Painter's Algorithm).

**Ключевые метрики:**
- Размер MVT тайла: 11–160 КБ (зависит от зума и плотности).
- Время генерации: 50–200 мс (без учета Disk I/O).
- Буфер геометрии: 0.125 тайла (~512 единиц MVT).
- Поддержка зумов: 0–18.

---

### [Глава 4: Оптимизации рендеринга](./04_rendering_optimizations.md)

**Содержание:**
- Проблема «исчезающих дорог» на Z14+ (диагностика, решение).
- Исправление структуры MVT (properties → flat attributes).
- Исправление Z-order в SQL (ORDER BY CASE highway).
- Исправление зазоров в зум-уровнях (maxzoom 14 → 14.1).
- Оптимизация ширины линий в map-style.js (highway-specific widths).

**Ключевые метрики:**
- До исправления: 0 дорог на Z14+ (фильтры не находили атрибуты).
- После исправления: 100% дорог видимы на всех зумах.
- Размер тайла Z14: 48 КБ (1490 объектов).
- Размер тайла Z15: 11 КБ (352 объекта).

---

### [Глава 5: Интеграция с клиентом](./05_client_integration.md)

**Содержание:**
- WebSocket-протокол для синхронизации LOD (ping, config, ack).
- Проблема JSON-парсинга (решение: обработка plain text).
- Soft BBox Check: просмотр данных вне границ без автозагрузки.
- Взаимодействие с Qt Client (data-ws-client.js, map-style.js).
- Компромиссы: редактирование кода клиента из зоны ответственности Data Processor.

**Ключевые метрики:**
- Задержка WebSocket ping: <50 мс.
- Размер LOD config: ~1.5 КБ (4 слоя, 14 типов дорог).
- Частота обновлений: при изменении конфигурации (событие tiles_invalidated).

---

### [Глава 6: Выводы и планы развития](./06_conclusions.md)

**Содержание:**
- Технический долг (кеширование MVT, предварительная генерация, CDN).
- Расширение функциональности (POI, здания, мультимодальные слои).
- Границы применимости (где подходит / не подходит).
- Честная самооценка (достижения и недостатки).

**Главный вывод:**
Система обменяла простоту на гибкость. Генерация «на лету» медленнее статических тайлов, но позволяет динамически менять стили и LOD без пересборки. Архитектура готова к масштабированию через кеширование и CDN.

---

## Технологический стек

**Таблица: Используемые технологии**

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| СУБД | PostgreSQL | 15 |
| Геопространственное расширение | PostGIS | 3.4 |
| API Server | FastAPI | 0.104 |
| Драйвер БД | asyncpg | 0.29 |
| Язык | Python | 3.11 |
| Контейнеризация | Docker | 24.0 |
| Источник данных | Overpass API | 0.7.61 |
| Формат тайлов | Mapbox Vector Tiles (MVT) | 2.1 |

---

## Ключевые файлы кодовой базы

**Таблица: Структура проекта**

| Файл | Описание |
|------|----------|
| `services/data-processor/src/main.py` | Точка входа, инициализация компонентов |
| `services/data-processor/src/handlers/mvt.py` | Генерация MVT-тайлов, управление LOD |
| `services/data-processor/src/handlers/tile_download.py` | Загрузка данных из Overpass API |
| `services/data-processor/src/db/queries.py` | SQL-запросы (GENERATE_MVT_TILE, BATCH_INSERT_WAYS) |
| `services/data-processor/src/api/tiles.py` | HTTP endpoints для тайлов, Soft BBox Check |
| `services/data-processor/src/api/websocket.py` | WebSocket для синхронизации LOD |
| `services/qt-client/assets/js/map-style.js` | Генератор стилей MapLibre GL (клиент) |
| `services/qt-client/assets/js/data-ws-client.js` | WebSocket-клиент (клиент) |

---

## Контакты и ссылки

**Репозиторий:** `L1CH7/magistracy_diplom_iu12`  
**Ветка:** `features/R-D-1/architecture`  
**Последний коммит:** 27.01.2026 (исправление MVT-структуры, Z-order, Soft BBox)

---

## Приложения

### Приложение A: Формулы и алгоритмы

**Tile Envelope (MVT):**

$$
Envelope = ST\_TileEnvelope(z, x, y, margin)
$$

$$
margin = 0.125 \quad (\text{1/8 размера тайла})
$$

**Bounding Box для загрузки:**

$$
BBOX = (west, south, east, north), \quad step = 0.05°
$$

**Размер тайла на широте Москвы (55.75°):**

$$
Width_{km} = 0.05° \times 111.32 \times \cos(55.75°) \approx 5.5 \text{ км}
$$

$$
Height_{km} = 0.05° \times 111.32 \approx 3.7 \text{ км}
$$

### Приложение B: SQL-запросы

**Генерация MVT-тайла:**

```{.sql caption="GENERATE_MVT_TILE из queries.py"}
SELECT ST_AsMVT(tile, 'ways', 4096, 'geom')
FROM (
    SELECT
        osm_id,
        highway,
        name,
        tags->>'oneway' AS oneway,
        maxspeed,
        ST_AsMVTGeom(
            geom_3857,
            ST_TileEnvelope($1, $2, $3),
            4096,
            256,
            true
        ) AS geom
    FROM osm.ways
    WHERE 
        geom_3857 && ST_TileEnvelope($1, $2, $3, margin => 0.125)
        AND highway IS NOT NULL
        AND (
            'ALL' = ANY($4::text[])
            OR highway = ANY($4::text[])
        )
        ORDER BY
            CASE highway
                WHEN 'motorway' THEN 10
                WHEN 'trunk' THEN 9
                WHEN 'primary' THEN 8
                WHEN 'secondary' THEN 7
                WHEN 'tertiary' THEN 6
                WHEN 'unclassified' THEN 5
                WHEN 'residential' THEN 4
                WHEN 'service' THEN 3
                WHEN 'track' THEN 2
                WHEN 'path' THEN 1
                WHEN 'footway' THEN 1
                ELSE 0
            END ASC
) AS tile
WHERE geom IS NOT NULL
```

**Batch Insert Ways:**

```{.sql caption="BATCH_INSERT_WAYS из queries.py"}
INSERT INTO osm.ways (
    osm_id, geom, geom_3857, tags, highway, name, lanes, maxspeed
) VALUES (
    $1,
    ST_GeomFromGeoJSON($2),
    ST_Transform(ST_GeomFromGeoJSON($2), 3857),
    $3::jsonb,
    $4, $5, $6::integer, $7
)
ON CONFLICT (osm_id) DO UPDATE SET
    geom = EXCLUDED.geom,
    geom_3857 = EXCLUDED.geom_3857,
    tags = EXCLUDED.tags,
    highway = EXCLUDED.highway,
    name = EXCLUDED.name,
    lanes = EXCLUDED.lanes,
    maxspeed = EXCLUDED.maxspeed
```

---

**Дата создания отчета:** 05.02.2026  
**Версия:** 2.2 (следует промпту Antigravity Report Prompt 2.2)
