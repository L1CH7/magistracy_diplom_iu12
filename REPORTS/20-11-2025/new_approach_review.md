# Ревью: new_approach.md

## Общая оценка: ⭐⭐⭐⭐⭐ (Excellent)

Документ крайне качественный, подкреплён ссылками на реальные исследования и best practices. Архитектура полностью соответствует production-ready системам (OpenMapTiles, etc).

---

## По блокам

### 1. Тайлы vs полный датасет ✅

**Анализ:** Правильно!

- ✅ MapLibre действительно работает с `/z/x/y.mvt` схемой
- ✅ Прогрессивная загрузка - ключевой момент для UX
- ✅ ST_AsMVT производительность (140-560ms) - отлично подтверждено источниками

**Добавить:**
- Упомянуть `overzooming` - когда на z>14 используем тайлы z=14 с клиентским масштабированием (экономия генерации)
- `simplification` на низких зумах - ST_Simplify для уменьшения детализации

---

### 2. Слои данных (3 сущности) ✅

**Архитектура идеальна!**

```
OSM RAW → ROUTING GRAPH → MVT (on-the-fly)
```

#### 2.1 OSM данные - источник истины ✅

```sql
CREATE TABLE osm_ways (
    osm_id BIGINT PRIMARY KEY,
    tags JSONB,
    geom GEOMETRY(LineString, 4326),
    bbox GEOMETRY(Polygon, 4326),  -- 👍 для ST_Intersects
    updated_at TIMESTAMP
);
```

**Отлично:**
- ✅ `bbox` для быстрой фильтрации
- ✅ GIN index на `tags` - быстрый поиск по highway/name

**Предложения:**
1. Добавить `osm_nodes` таблицу (нужна для топологии графа):
```sql
CREATE TABLE osm_nodes (
    osm_id BIGINT PRIMARY KEY,
    geom GEOMETRY(Point, 4326),
    tags JSONB
);
```

2. **osm2pgsql** - правильный выбор! Но добавить:
```lua
-- mapping.lua для osm2pgsql flex
osm2pgsql.define_way_table('osm_ways', {
    { column = 'osm_id', type = 'bigint', not_null = true },
    { column = 'tags', type = 'jsonb' },
    { column = 'geom', type = 'linestring', projection = 4326 },
    { column = 'bbox', sql_type = 'geometry(polygon, 4326)' },
    { column = 'updated_at', type = 'timestamp', sql_type = 'timestamp DEFAULT NOW()' }
})

function osm2pgsql.process_way(object)
    if object.tags.highway then
        osm2pgsql.ways:add_row({
            osm_id = object.id,
            tags = object.tags,
            geom = object:as_linestring(),
            bbox = object:as_polygon():envelope()
        })
    end
end
```

3. **Динамическая загрузка bbox** - функция `reload_osm_bbox()` отличная, но:
```sql
-- Добавить логирование
CREATE TABLE osm_reload_log (
    bbox GEOMETRY(Polygon, 4326),
    ways_deleted INTEGER,
    ways_inserted INTEGER,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

#### 2.2 Routing Graph ✅

**Структура идеальна:**

```sql
CREATE TABLE routing_edges (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT REFERENCES osm_ways(osm_id),
    source BIGINT,
    target BIGINT,
    cost DOUBLE PRECISION,
    reverse_cost DOUBLE PRECISION,
    ...
);
```

**Критический момент - триггер синхронизации:**

Твой триггер:
```sql
CREATE TRIGGER trg_sync_routing
AFTER INSERT OR UPDATE OR DELETE ON osm_ways
FOR EACH ROW EXECUTE FUNCTION sync_routing_graph();
```

**Проблема:** Триггер будет срабатывать для КАЖДОГО way при массовой загрузке (100k INSERT = 100k триггеров).

**Решение:**
1. **Отключить триггер при массовой загрузке:**
```sql
ALTER TABLE osm_ways DISABLE TRIGGER trg_sync_routing;
-- osm2pgsql импорт
ALTER TABLE osm_ways ENABLE TRIGGER trg_sync_routing;
```

2. **Batch rebuild после импорта:**
```sql
CREATE OR REPLACE FUNCTION rebuild_routing_graph_batch(
    bbox_geom GEOMETRY DEFAULT NULL
) RETURNS void AS $$
BEGIN
    -- Удалить старые ребра в bbox
    IF bbox_geom IS NOT NULL THEN
        DELETE FROM routing_edges
        WHERE osm_id IN (
            SELECT osm_id FROM osm_ways
            WHERE ST_Intersects(geom, bbox_geom)
        );
    ELSE
        TRUNCATE routing_edges;
    END IF;
    
    -- Построить топологию через pgr_createTopology
    -- (или custom логика построения графа)
    PERFORM pgr_createTopology(
        'routing_edges',
        0.00001,  -- tolerance для snap
        'geom',
        'id',
        'source',
        'target'
    );
END;
$$ LANGUAGE plpgsql;
```

3. **Интеграция с osm2pgsql:**
```bash
# После импорта OSM
osm2pgsql -d mydb -O flex -S mapping.lua region.osm.pbf

# Batch rebuild графа
psql -d mydb -c "SELECT rebuild_routing_graph_batch()"
```

**Дополнительно - cost calculation:**

```sql
-- Функция расчета cost (время в секундах)
CREATE OR REPLACE FUNCTION calculate_edge_cost(
    length_meters FLOAT,
    maxspeed INTEGER,
    highway TEXT
) RETURNS FLOAT AS $$
DECLARE
    speed_kmh INTEGER;
BEGIN
    -- Приоритет: maxspeed tag > default по highway
    speed_kmh := COALESCE(
        maxspeed,
        CASE highway
            WHEN 'motorway' THEN 110
            WHEN 'trunk' THEN 100
            WHEN 'primary' THEN 80
            WHEN 'secondary' THEN 60
            WHEN 'tertiary' THEN 50
            WHEN 'residential' THEN 30
            WHEN 'living_street' THEN 20
            ELSE 40
        END
    );
    
    -- Время = расстояние (км) / скорость (км/ч) * 3600 (секунд)
    RETURN (length_meters / 1000.0) / speed_kmh * 3600;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Использование при построении графа
INSERT INTO routing_edges (osm_id, source, target, cost, reverse_cost, ...)
SELECT 
    osm_id,
    source_node,
    target_node,
    calculate_edge_cost(
        ST_Length(geom::geography),
        (tags->>'maxspeed')::INTEGER,
        tags->>'highway'
    ) AS cost,
    CASE 
        WHEN tags->>'oneway' = 'yes' THEN -1  -- нельзя ехать назад
        ELSE calculate_edge_cost(...)
    END AS reverse_cost,
    ...
FROM osm_ways;
```

#### 2.3 MVT Cache ✅

**Отличный анализ!**

- ✅ NGINX/Redis лучше PostgreSQL для кеша
- ✅ ST_AsMVT достаточно быстрый для on-the-fly генерации
- ✅ Инвалидация кеша сложна

**Предложение:** Hybrid подход:

1. **NGINX кеш для популярных зумов (z=10-14):**
```nginx
location ~ ^/tiles/(?<z>1[0-4])/(?<x>\d+)/(?<y>\d+).mvt$ {
    proxy_cache tiles_cache;
    proxy_cache_valid 200 7d;
    proxy_pass http://postgis_backend;
}
```

2. **On-the-fly для высоких зумов (z=15-18):**
```nginx
location ~ ^/tiles/(?<z>1[5-8])/(?<x>\d+)/(?<y>\d+).mvt$ {
    proxy_cache off;  # Слишком много комбинаций для кеша
    proxy_pass http://postgis_backend;
}
```

---

### 3. Оптимальная архитектура API ✅

**SQL функция `get_tile_mvt()` отличная!**

**Добавить simplification на низких зумах:**

```sql
CREATE OR REPLACE FUNCTION get_tile_mvt(
    z INT, x INT, y INT
) RETURNS BYTEA AS $$
BEGIN
    RETURN (
        SELECT ST_AsMVT(tile, 'roads', 4096, 'geom')
        FROM (
            SELECT
                osm_id,
                jsonb_build_object(
                    'highway', tags->>'highway',
                    'name', tags->>'name',
                    'oneway', tags->>'oneway'
                ) AS properties,
                ST_AsMVTGeom(
                    -- Упрощение на низких зумах
                    ST_Transform(
                        CASE 
                            WHEN z < 10 THEN ST_Simplify(geom, 0.001)
                            WHEN z < 12 THEN ST_Simplify(geom, 0.0001)
                            ELSE geom
                        END,
                        3857
                    ),
                    ST_TileEnvelope(z, x, y),
                    4096,
                    256,
                    true
                ) AS geom
            FROM osm_ways
            WHERE 
                geom && ST_Transform(ST_TileEnvelope(z, x, y), 4326)
                AND tags->>'highway' IS NOT NULL
                -- Фильтр дорог по зуму
                AND (
                    z >= 14 
                    OR tags->>'highway' IN ('motorway', 'trunk', 'primary')
                )
                -- Не рисуем footway/path на низких зумах
                AND (
                    z >= 16
                    OR tags->>'highway' NOT IN ('footway', 'path', 'steps')
                )
        ) AS tile
        WHERE geom IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;
```

**Node.js сервер - отлично, но добавить:**

```javascript
app.get('/tiles/:z/:x/:y.mvt', async (req, res) => {
  const { z, x, y } = req.params;
  
  // Валидация параметров
  const zoom = parseInt(z);
  const tileX = parseInt(x);
  const tileY = parseInt(y);
  
  if (zoom < 0 || zoom > 18 || 
      tileX < 0 || tileX >= Math.pow(2, zoom) ||
      tileY < 0 || tileY >= Math.pow(2, zoom)) {
    return res.status(400).send('Invalid tile coordinates');
  }
  
  try {
    const result = await pool.query(
      'SELECT get_tile_mvt($1, $2, $3) AS mvt',
      [zoom, tileX, tileY]
    );
    
    const tile = result.rows[0].mvt;
    
    if (!tile || tile.length === 0) {
      // 204 No Content - валидный тайл но пустой
      res.setHeader('Cache-Control', 'public, max-age=3600');
      return res.status(204).send();
    }
    
    res.setHeader('Content-Type', 'application/x-protobuf');
    res.setHeader('Content-Encoding', 'gzip');
    res.setHeader('Cache-Control', 'public, max-age=604800');
    res.setHeader('Access-Control-Allow-Origin', '*');  // CORS для клиента
    res.send(tile);
    
  } catch (err) {
    console.error(`Error generating tile ${z}/${x}/${y}:`, err);
    res.status(500).send('Error generating tile');
  }
});

// Healthcheck endpoint
app.get('/health', async (req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({ status: 'ok', database: 'connected' });
  } catch (err) {
    res.status(503).json({ status: 'error', database: 'disconnected' });
  }
});
```

---

### 4. Системы координат ✅

**Абсолютно правильно!**

- ✅ Хранить в 4326 (WGS84)
- ✅ Конвертация в 3857 (Web Mercator) on-the-fly
- ✅ ST_Transform очень быстрый

**Дополнительно:**
- Для расчета расстояний использовать `geography`:
```sql
-- Точная длина ребра (метры)
SELECT ST_Length(geom::geography) AS length_meters
FROM routing_edges;

-- Вместо
SELECT ST_Length(ST_Transform(geom, 3857));  -- приближенно
```

---

## Итоговая архитектура ✅

**Диаграмма отлична!** Только добавить:

```
┌──────────────────────────────────────────────────────────┐
│                     MapLibre Client                       │
│              Кеширует тайлы автоматически                 │
└─────────────────────┬────────────────────────────────────┘
                      │ GET /tiles/{z}/{x}/{y}.mvt
                      ↓
┌──────────────────────────────────────────────────────────┐
│             NGINX (кеш z=10-14, 7 дней)                   │
└─────────────────────┬────────────────────────────────────┘
                      │
                      ↓
┌──────────────────────────────────────────────────────────┐
│               Node.js/Go API сервер                       │
│         + WebSocket для real-time обновлений              │ <- NEW
└─────────────────────┬────────────────────────────────────┘
                      │
                      ↓
┌──────────────────────────────────────────────────────────┐
│                  PostgreSQL + PostGIS                     │
│                                                            │
│  ┌─────────────────────────────────────────────────┐    │
│  │ osm_ways (EPSG:4326)                             │    │
│  │ + osm_nodes (для топологии)                     │    │ <- NEW
│  └────────────┬────────────────────────────────────┘    │
│               │ batch rebuild после импорта               │ <- CHANGE
│               ↓                                            │
│  ┌─────────────────────────────────────────────────┐    │
│  │ routing_edges/nodes (EPSG:4326)                  │    │
│  │ + triggers DISABLED при массовой загрузке        │    │ <- NEW
│  └──────────────────────────────────────────────────┘    │
│                                                            │
│  ST_AsMVT() с simplification на низких зумах             │ <- NEW
└──────────────────────────────────────────────────────────┘
```

---

## Что добавить в текущий проект

### Критично (сейчас):

1. **Recovery механизм** (из моего ревью):
```python
async def _recover_failed_downloads(self):
    """Восстановить прерванные загрузки"""
    # Найти застрявшие тайлы в downloading
    # Перевести в failed
    # Разрешить redownload
```

2. **Redownload endpoint**:
```python
@app.post("/api/v1/tiles/{tile_key}/redownload")
async def redownload_tile(tile_key: str):
    # Сброс cached_tiles.status → pending
    # Очистка memory cache
    # Запуск загрузки
```

3. **Batch insert** (уже сделан ✅):
```python
await conn.executemany("INSERT INTO osm.ways ...", batch_data)
```

4. **Centralized state** (task_manager.py):
```python
class TaskManager:
    def __init__(self):
        self.tasks = {}  # {task_id: TaskState}
    
    def create_task(self, tile_key):
        task_id = str(uuid4())
        self.tasks[task_id] = {
            "tile_key": tile_key,
            "phase": "downloading",
            "progress": 0,
            "started_at": datetime.now(),
            "eta": None
        }
        return task_id
    
    def update_progress(self, task_id, progress, phase):
        self.tasks[task_id]["progress"] = progress
        self.tasks[task_id]["phase"] = phase
        # Calculate ETA...
```

### Среднесрочно:

5. **osm2pgsql integration** (вместо текущего парсинга):
```bash
# Импорт через osm2pgsql flex
osm2pgsql -d diplom -O flex -S mapping.lua moscow.osm.pbf

# Batch rebuild графа
psql -d diplom -c "SELECT rebuild_routing_graph_batch()"
```

6. **Триггер rebuild графа** (с batch режимом):
```sql
-- Триггер отключается при массовой загрузке
-- Batch rebuild вызывается вручную после импорта
```

7. **MVT simplification** (на низких зумах):
```sql
-- ST_Simplify в get_tile_mvt() функции
```

### Долгосрочно:

8. **NGINX кеш** (вместо in-memory cache):
```nginx
proxy_cache_path /var/cache/nginx/tiles ...
```

9. **WebSocket notifications** (для real-time обновлений клиента):
```javascript
// Клиент получает уведомления о новых тайлах
ws.onmessage = (msg) => {
    const { tile_key, status } = JSON.parse(msg.data);
    if (status === 'complete') {
        map.getSource('roads').reload();
    }
};
```

---

## Финальные рекомендации

### Текущий проект (data-processor):

**Сейчас:**
```
services/data-processor/
├── src/
│   ├── manager.py        # 1300+ строк, монолитный
│   └── main.py           # FastAPI endpoints
```

**Рефакторинг:**
```
services/data-processor/
├── src/
│   ├── handlers/
│   │   ├── osm_importer.py       # osm2pgsql wrapper
│   │   ├── tile_downloader.py    # Overpass API загрузка
│   │   ├── graph_builder.py      # OSM → routing_edges
│   │   └── mvt_generator.py      # ST_AsMVT wrapper
│   ├── state/
│   │   ├── task_manager.py       # Centralized state
│   │   └── progress_tracker.py   # Progress + ETA
│   ├── db/
│   │   ├── pool.py               # asyncpg pool
│   │   ├── queries.py            # SQL functions
│   │   └── migrations/           # Schema migrations
│   ├── api/
│   │   ├── tiles.py              # Tile management
│   │   ├── status.py             # Real-time status
│   │   └── tasks.py              # Task operations
│   └── main.py                   # FastAPI app
```

### Миграция:

**Фаза 1 (текущая):**
- ✅ Batch insert (executemany)
- ✅ Non-blocking endpoints (asyncio.create_task)
- ❌ Recovery механизм
- ❌ Redownload endpoint

**Фаза 2:**
- ❌ Handlers refactoring
- ❌ Task manager
- ❌ Progress tracking

**Фаза 3:**
- ❌ osm2pgsql integration
- ❌ Graph auto-rebuild (triggers)
- ❌ NGINX cache

**Фаза 4:**
- ❌ WebSocket notifications
- ❌ MVT simplification
- ❌ Production deployment

---

## Оценка документа new_approach.md

### Сильные стороны:
- ✅ Подтверждение источниками (20+ ссылок)
- ✅ Production-ready архитектура
- ✅ Правильные best practices
- ✅ Детальные SQL примеры
- ✅ Чёткое разделение слоёв

### Слабые стороны (minor):
- ⚠️ Триггер синхронизации не учитывает массовую загрузку
- ⚠️ Нет osm_nodes таблицы (нужна для графа)
- ⚠️ Нет упоминания simplification на низких зумах

### Итого:
**9.5/10** - Отличный документ, готов к имплементации с минорными доработками выше.

---

**Следующий шаг:** Внедрить критичные изменения (recovery, redownload, task_manager), затем переходить к osm2pgsql integration.
