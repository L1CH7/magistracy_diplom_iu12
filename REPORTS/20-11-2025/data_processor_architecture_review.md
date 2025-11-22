# Ревью архитектуры Data Processor

## Текущие проблемы

### 1. **Производительность**
- ❌ Сохранение 100k ways крайне долгое (до внедрения batch insert)
- ✅ **РЕШЕНИЕ**: executemany в `_save_ways_to_db()` даст 100x ускорение

### 2. **Дублирование эндпоинтов**
```python
@app.post("/api/v1/data/download-tile")           # Query params: ?lon=X&lat=Y
@app.post("/api/v1/data/tile/{lon}/{lat}/ensure")  # Path params: /{lon}/{lat}/ensure
```
**Зачем?** Обратная совместимость - клиент использует `/download-tile?lon=`, новый код предпочитает REST path params.

**РЕКОМЕНДАЦИЯ**: Убрать дублирование, мигрировать клиент на один стиль (REST path params лучше).

### 3. **FastAPI vs Handlers**
**FastAPI + текущая архитектура:**
- ✅ Простота разработки (декораторы, типизация, автодокументация)
- ✅ Async/await из коробки
- ❌ Блокируется долгими операциями (до внедрения asyncio.create_task)
- ❌ Нет встроенного механизма фоновых задач с мониторингом

**Handlers подход (альтернатива):**
```python
class TileDownloadHandler:
    def __init__(self, db_pool, state_manager):
        self.db = db_pool
        self.state = state_manager  # Centralized state tracking
    
    async def handle(self, tile_key):
        # 1. Update state: "downloading"
        await self.state.mark_tile_downloading(tile_key)
        
        # 2. Download
        try:
            osm_data = await self._download_osm(tile_key)
            await self.state.update_progress(tile_key, 50, "parsing")
            
            # 3. Save
            await self._save_ways(osm_data)
            await self.state.mark_tile_complete(tile_key)
        except Exception as e:
            await self.state.mark_tile_failed(tile_key, str(e))
```

**Преимущества handlers:**
- ✅ Централизованное управление состоянием
- ✅ Легко добавить retry логику
- ✅ Чистое разделение ответственности
- ✅ Проще тестировать

**Реализация в проекте:**
1. `handlers/tile_download_handler.py` - загрузка OSM
2. `handlers/graph_build_handler.py` - конвертация OSM → граф
3. `handlers/mvt_generation_handler.py` - генерация MVT
4. `state/task_manager.py` - хранит состояние всех задач (downloading, processing, complete, failed)
5. FastAPI становится тонким слоем над handlers:
```python
@app.post("/api/v1/tiles/download/{lon}/{lat}")
async def download_tile(lon: float, lat: float):
    tile_key = (lon, lat)
    task_id = await tile_handler.start_download(tile_key)
    return {"task_id": task_id, "status": "started"}

@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    return await state_manager.get_task(task_id)
```

## Критические требования

### 4. **Прозрачность состояния**

**Что должно быть доступно всегда (даже во время загрузки):**
```json
{
  "tiles": {
    "downloading": [
      {
        "tile_key": "37.60_55.75",
        "progress": 45,
        "phase": "saving",
        "ways_downloaded": 20226,
        "ways_saved": 9102,
        "estimated_time_remaining": "2m 15s",
        "started_at": "2025-11-19T17:48:30Z"
      }
    ],
    "processing": [...],  // OSM → graph conversion
    "complete": 153,
    "failed": [
      {
        "tile_key": "37.20_55.60",
        "error": "DNS resolution failed",
        "attempts": 15,
        "last_attempt": "2025-11-19T17:51:00Z"
      }
    ]
  },
  "stats": {
    "total_ways": 150000,
    "total_nodes": 50000,
    "total_edges": 120000,
    "db_size_mb": 450
  }
}
```

**Реализация:**
- `state/task_tracker.py` - хранит все активные задачи в памяти + Redis
- Периодическое сохранение в DB (каждые 10s)
- `/api/v1/status` - мгновенный ответ из памяти (не блокируется)

### 5. **Устойчивость к сбоям**

**Проблемы:**
- ❌ Прерванная загрузка → в cached_tiles status="downloading" навсегда
- ❌ Нет механизма recovery после рестарта
- ❌ Нельзя перезагрузить тайл без очистки БД

**РЕШЕНИЕ - Recovery механизм:**

```python
async def _recover_failed_downloads(self):
    """Run on startup - recover interrupted downloads"""
    async with self.db_pool.acquire() as conn:
        # Find tiles stuck in "downloading" state
        stuck_tiles = await conn.fetch("""
            SELECT tile_key, updated_at 
            FROM osm.cached_tiles 
            WHERE download_status = 'downloading'
            AND updated_at < NOW() - INTERVAL '5 minutes'
        """)
        
        for row in stuck_tiles:
            tile_key = self._str_to_tile_key(row["tile_key"])
            logger.warning(f"Recovering stuck tile {row['tile_key']}")
            
            # Reset to failed, allow redownload
            await conn.execute("""
                UPDATE osm.cached_tiles 
                SET download_status = 'failed',
                    error_message = 'Interrupted by restart'
                WHERE tile_key = $1
            """, row["tile_key"])
            
            # Clear from memory cache
            self.processed_tiles_cache.pop(tile_key, None)
```

**Запуск при старте data-processor:**
```python
async def startup_event():
    await data_manager.connect_db()
    await data_manager._recover_failed_downloads()  # NEW
    await data_manager._preload_tiles_cache()
```

### 6. **Идемпотентность загрузки**

**Требование:** Повторная загрузка перезаписывает данные корректно:
- Загрузили bbox 0.2×0.2 → 20k ways
- Перезагрузили bbox 1.0×0.9 → 100k ways
- Результат: только актуальные ways

**Решение уже есть:**
```sql
INSERT INTO osm.ways (osm_id, ...) VALUES (...)
ON CONFLICT (osm_id) DO UPDATE SET
    geom = EXCLUDED.geom,
    tags = EXCLUDED.tags,
    ...
```
✅ `ON CONFLICT` гарантирует перезапись.

**Добавить:**
```python
@app.post("/api/v1/tiles/{tile_key}/redownload")
async def redownload_tile(tile_key: str):
    """Force redownload of specific tile (даже если complete)"""
    # 1. Mark as pending
    await conn.execute("""
        UPDATE osm.cached_tiles 
        SET download_status = 'pending',
            updated_at = NOW()
        WHERE tile_key = $1
    """, tile_key)
    
    # 2. Clear memory cache
    tile_tuple = _str_to_tile_key(tile_key)
    self.processed_tiles_cache.pop(tile_tuple, None)
    
    # 3. Start download
    asyncio.create_task(ensure_tile_downloaded(tile_tuple))
    
    return {"status": "redownload_started", "tile_key": tile_key}
```

### 7. **Читабельность БД во время загрузки**

**Проблема:** Клиент не может читать БД пока data-processor занят.

**Причина:** До внедрения batch insert - долгие транзакции блокируют SELECT.

**РЕШЕНИЕ:**
1. ✅ Batch insert - короткие транзакции (<10s)
2. ✅ `asyncio.create_task()` - MVT не ждёт загрузки
3. **Добавить:** READ UNCOMMITTED для MVT:
```python
async def get_mvt_tile(self, z, x, y):
    async with self.db_pool.acquire() as conn:
        # Не блокируется записью
        await conn.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        mvt = await conn.fetchval("SELECT ST_AsMVT(...) FROM osm.ways ...")
```

## Таблицы БД

### Твоё видение (правильное):

**1. `osm.ways` - источник истины**
```sql
CREATE TABLE osm.ways (
    osm_id BIGINT PRIMARY KEY,
    geom GEOMETRY(LineString, 4326),
    geom_3857 GEOMETRY(LineString, 3857),  -- Pre-computed for MVT
    tags JSONB,
    highway TEXT,
    name TEXT,
    lanes INTEGER,
    maxspeed TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX ON osm.ways USING GIST (geom_3857);  -- MVT performance
```

**2. `routing.graph_edges` - обработанный граф (для маршрутизации)**
```sql
CREATE TABLE routing.graph_edges (
    id SERIAL PRIMARY KEY,
    osm_way_id BIGINT REFERENCES osm.ways(osm_id) ON DELETE CASCADE,
    source_node BIGINT,
    target_node BIGINT,
    cost_forward FLOAT,  -- Время прохождения (секунды)
    cost_reverse FLOAT,
    length_meters FLOAT,
    bearing FLOAT,  -- Азимут (ST_Azimuth)
    capacity INTEGER,  -- Пропускная способность
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX ON routing.graph_edges (source_node);
CREATE INDEX ON routing.graph_edges (target_node);
CREATE INDEX ON routing.graph_edges (osm_way_id);  -- Rebuild trigger
```

**Триггер:** При UPDATE osm.ways → пересчитать routing.graph_edges:
```sql
CREATE OR REPLACE FUNCTION rebuild_graph_edge()
RETURNS TRIGGER AS $$
BEGIN
    -- Mark edge for rebuild
    UPDATE routing.graph_edges 
    SET cost_forward = NULL  -- NULL = needs rebuild
    WHERE osm_way_id = NEW.osm_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER osm_ways_updated
AFTER UPDATE ON osm.ways
FOR EACH ROW
EXECUTE FUNCTION rebuild_graph_edge();
```

**3. `osm.cached_tiles` - метаданные тайлов (опционально)**
```sql
CREATE TABLE osm.cached_tiles (
    tile_key TEXT PRIMARY KEY,
    download_status TEXT,  -- 'pending' | 'downloading' | 'complete' | 'failed'
    ways_count INTEGER,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**MVT:** Генерируется on-the-fly из `osm.ways`, НЕ хранится:
```sql
SELECT ST_AsMVT(tile, 'roads', 4096, 'geom_3857') AS mvt
FROM (
    SELECT 
        osm_id,
        highway,
        name,
        ST_AsMVTGeom(geom_3857, ...) AS geom_3857
    FROM osm.ways
    WHERE geom_3857 && ST_MakeEnvelope(...)
) AS tile;
```

## Минимальная архитектура

### Упрощённая структура:

```
data-processor/
├── src/
│   ├── handlers/
│   │   ├── tile_download_handler.py     # OSM download + save
│   │   ├── graph_builder_handler.py     # OSM → routing.graph_edges
│   │   └── mvt_handler.py               # MVT generation
│   ├── state/
│   │   ├── task_manager.py              # Centralized task state
│   │   └── progress_tracker.py          # Progress + ETA
│   ├── api/
│   │   ├── tiles.py                     # Tile endpoints
│   │   ├── status.py                    # Real-time status
│   │   └── tasks.py                     # Task management
│   ├── db/
│   │   ├── pool.py                      # DB connection pool
│   │   └── queries.py                   # Reusable SQL
│   └── main.py                          # FastAPI app
```

### Endpoints (минимальный набор):

**Download & Status:**
```python
POST   /api/v1/tiles/download/{lon}/{lat}      # Start download
POST   /api/v1/tiles/{tile_key}/redownload     # Force redownload
GET    /api/v1/tiles/{tile_key}/status         # Tile status
GET    /api/v1/status                          # Global status (instant)
```

**MVT:**
```python
GET    /api/v1/tiles/{z}/{x}/{y}.mvt           # Vector tiles
```

**Tasks:**
```python
GET    /api/v1/tasks                           # All active tasks
GET    /api/v1/tasks/{task_id}                 # Task details
DELETE /api/v1/tasks/{task_id}                 # Cancel task
```

**Graph (маршрутизация):**
```python
POST   /api/v1/graph/rebuild/{tile_key}        # Rebuild graph for tile
GET    /api/v1/graph/stats                     # Graph statistics
```

## Рекомендации

### Немедленно (критично):
1. ✅ **Batch insert** - внедрить executemany (уже сделано)
2. ✅ **Non-blocking endpoints** - asyncio.create_task (уже сделано)
3. ❌ **Recovery механизм** - восстановление после рестарта
4. ❌ **Centralized state** - task_manager.py для мониторинга

### Среднесрочно:
5. ❌ **Redownload endpoint** - перезагрузка без очистки БД
6. ❌ **Progress tracking** - детальный прогресс с ETA
7. ❌ **Handlers refactoring** - разделение на TileDownloadHandler, GraphBuilderHandler

### Долгосрочно:
8. ❌ **Graph auto-rebuild** - триггеры на osm.ways → routing.graph_edges
9. ❌ **Redis state** - персистентное хранилище состояния
10. ❌ **WebSocket notifications** - клиент получает обновления без polling

## Выводы

### FastAPI или Handlers?
**Ответ:** FastAPI + Handlers.
- FastAPI - тонкий HTTP слой
- Handlers - бизнес-логика с centralised state
- Лучшее из обоих миров

### Производительность?
- ✅ Batch insert решает (100x ускорение)
- ✅ asyncio.create_task решает блокировку
- ⚠️ READ UNCOMMITTED для MVT во время записи

### Устойчивость?
- ❌ Нужен recovery механизм
- ❌ Нужен redownload endpoint
- ✅ ON CONFLICT уже обеспечивает идемпотентность

### Прозрачность?
- ❌ Нужен /api/v1/status с реальным прогрессом
- ❌ Нужен task_manager.py для централизованного состояния

---

**Файл new_approach.md не найден - создай его и поделись, дам детальное ревью!**
