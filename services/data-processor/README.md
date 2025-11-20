# Data Processor - Refactored Architecture

## Обзор

Data Processor - сервис для управления OSM данными и генерации MVT тайлов.

**Версия:** 2.0.0  
**Архитектура:** Модульная (handlers/state/db/api)  
**Ключевые особенности:**
- ✅ Batch insert (100x ускорение)
- ✅ Task tracking с ETA
- ✅ Recovery механизм
- ✅ Non-blocking API
- ✅ Централизованные SQL
- ✅ Redownload без очистки БД

## Структура

```
src/
├── db/
│   ├── pool.py         # Database connection pool
│   └── queries.py      # Centralized SQL queries
├── state/
│   └── task_manager.py # Task tracking + progress + ETA
├── handlers/
│   ├── tile_download.py # OSM download logic
│   └── mvt.py           # MVT generation
├── api/
│   ├── status.py        # Status endpoints
│   └── tiles.py         # Tiles endpoints
└── main.py              # FastAPI application
```

## API Endpoints

### Status API

```bash
# Глобальный статус системы
GET /api/v1/status
→ {tasks: {statistics, by_phase}, database: {ways, tiles_cached, ...}}

# Все задачи
GET /api/v1/tasks
→ {downloading: [...], saving: [...], complete: [...], failed: [...]}

# Конкретная задача
GET /api/v1/tasks/{task_id}
→ {task_id, phase, progress, eta, items_processed, items_total, ...}
```

### Tiles API

```bash
# Загрузка тайла
POST /api/v1/tiles/download?lon=37.6&lat=55.75&bbox_size=0.2
→ {status: "started", tile_key: "37.60_55.75", bbox: [...]}

# Принудительная перезагрузка
POST /api/v1/tiles/{tile_key}/redownload
→ {status: "redownload_started", tile_key: "..."}

# MVT тайл
GET /api/v1/tiles/{z}/{x}/{y}.mvt
→ Protocol Buffer (application/x-protobuf)
```

### Health Check

```bash
GET /health
→ {status: "healthy", service: "data-processor", database: "connected"}
```

## Тестирование

```bash
# Запуск тестов
./scripts/test_data_processor.sh
```

Тесты проверяют:
1. Health check
2. Status API
3. Tasks API
4. Tile download
5. Progress tracking
6. MVT generation
7. Redownload
8. Recovery mechanism

## Task Manager

TaskManager отслеживает все операции в реальном времени:

```python
class TaskState:
    task_id: str                    # Уникальный ID
    phase: TaskPhase                # pending|downloading|saving|complete|failed
    progress: float                 # 0-100%
    items_total: int                # Всего элементов
    items_processed: int            # Обработано
    started_at: datetime            # Время старта
    eta: datetime                   # Расчётное время завершения
    error: Optional[str]            # Ошибка (если есть)
```

**Автоматический расчёт ETA:**
```python
# TaskManager рассчитывает ETA на основе скорости обработки
elapsed = now - started_at
rate = items_processed / elapsed  # items/sec
remaining = items_total - items_processed
eta = now + timedelta(seconds=remaining/rate)
```

## Recovery Механизм

При запуске data-processor проверяет "застрявшие" тайлы:

```python
async def recover_failed_downloads(db, task_manager):
    """
    Находит тайлы в статусе 'downloading' > 5 минут
    → Помечает как 'failed'
    → Позволяет перезагрузить через /redownload
    """
    stuck_tiles = await conn.fetch(OSMQueries.FIND_STUCK_TILES)
    for tile in stuck_tiles:
        await conn.execute(OSMQueries.RESET_STUCK_TILE, tile["tile_key"])
```

**Результат:** Система автоматически восстанавливается после сбоя.

## Batch Insert

Вместо 20k одиночных INSERT → один пакетный:

```python
# Старая версия (МЕДЛЕННО):
for way in ways:  # 20k iterations
    await conn.execute("INSERT INTO osm.ways ...")
# Время: ~10 минут

# Новая версия (БЫСТРО):
batch_data = [(osm_id, geom, tags, ...) for way in ways]
await conn.executemany(OSMQueries.BATCH_INSERT_WAYS, batch_data)
# Время: ~6 секунд

# Ускорение: 100x!
```

## Миграции

```bash
# Применить миграции
docker compose exec postgis psql -U diplom -d osm < migrations/014_fix_cached_tiles_column_types.sql
```

**Миграция 014:** Исправление типов колонок `download_status` и `download_error` (varchar → text)

## Конфигурация

Environment variables:

```bash
DB_HOST=postgis
DB_PORT=5432
DB_NAME=osm
DB_USER=diplom
DB_PASSWORD=diplom_pass
```

Overpass servers:
- https://overpass-api.de
- https://overpass.kumi.systems
- https://overpass.openstreetmap.ru

## Производительность

### Загрузка тайла (0.15° ≈ 15km)

**Старая архитектура:**
- Downloading: ~46s
- Saving: ~10 минут (single INSERT)
- **Total: ~11 минут**

**Новая архитектура:**
- Downloading: ~46s
- Saving: ~6 секунд (batch insert)
- **Total: ~52 секунды**

**Ускорение: 12x!**

### Параллельная загрузка

**Старая:**
- ❌ Загрузка блокирует другие задачи
- ❌ `/status` не отвечает во время работы

**Новая:**
- ✅ Загрузка не блокирует
- ✅ `/status` отвечает мгновенно
- ✅ Параллельная загрузка нескольких тайлов

## Разработка

### Добавление нового endpoint

1. Создать handler в `src/handlers/`
2. Добавить SQL в `src/db/queries.py`
3. Создать endpoint в `src/api/`
4. Подключить router в `src/main.py`

### Добавление нового SQL query

```python
# src/db/queries.py
class OSMQueries:
    MY_NEW_QUERY = """
        SELECT ...
        FROM osm.ways
        WHERE ...
    """
```

### Тестирование handler

```python
# tests/test_tile_download.py
import pytest
from src.handlers.tile_download import TileDownloadHandler

@pytest.mark.asyncio
async def test_download_tile(db_pool, task_manager):
    handler = TileDownloadHandler(db_pool, task_manager, ...)
    result = await handler.download_tile((37.6, 55.75), bbox)
    assert result["status"] == "complete"
```

## Troubleshooting

### "Tile download stuck in 'downloading'"

Recovery механизм автоматически исправит при рестарте:
```bash
docker compose restart data-processor
```

### "MVT tile returns 204 No Content"

Тайл пустой (нет дорог в этом bbox). Это нормально для океанов/лесов.

### "Task active but not in downloading/saving"

Задача застряла. Проверить логи:
```bash
docker compose logs data-processor | grep ERROR
```

## Roadmap

- [ ] Graph builder handler (routing_edges)
- [ ] osm2pgsql integration
- [ ] WebSocket notifications
- [ ] Redis state persistence
- [ ] Unit tests
- [ ] NGINX cache integration
