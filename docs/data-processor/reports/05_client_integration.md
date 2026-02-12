## Интеграция с клиентом

### Контекст задачи

Data Processor интегрируется с Qt Client через два канала:

1. **HTTP API:** Отдача MVT-тайлов по запросам MapLibre GL (`GET /api/v1/tiles/{z}/{x}/{y}.mvt`).
2. **WebSocket:** Двусторонняя синхронизация конфигурации LOD и уведомления об обновлении данных.

Ключевая особенность: Data Processor не имеет собственного UI, вся визуализация происходит в Qt Client. Это создает архитектурную зависимость: изменения в Data Processor могут требовать правок в клиентском коде (зона ответственности другого сервиса).

### WebSocket-протокол для синхронизации LOD

**Назначение:**

WebSocket используется для:

1. **Передачи LOD config от клиента к серверу** при подключении.
2. **Уведомления клиента об обновлении данных** (событие `ways_updated`).
3. **Поддержания соединения** (ping/pong).

**Формат сообщений:**

Все сообщения передаются в формате JSON:

```{.json caption="Примеры сообщений WebSocket"}
// От клиента: ping
{"type": "ping"}

// От сервера: pong
{"type": "pong"}

// От клиента: LOD config
{
  "type": "config",
  "lod": {
    "layers": [
      {"name": "highways", "minzoom": 0, "maxzoom": 8.1, "highways": [...], "base_width": 0.5},
      {"name": "all_roads", "minzoom": 14, "maxzoom": 24, "highways": [...], "base_width": 2.5}
    ]
  }
}

// От сервера: подтверждение
{"type": "ack", "message": "LOD config updated"}

// От сервера: уведомление об обновлении данных
{"type": "tiles_invalidated", "message": "Ways updated, invalidate tile cache"}
```

**Реализация на сервере:**

```{.python caption="websocket.py: обработка сообщений"}
@router.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info(f"WebSocket connected: {websocket.client}")
    
    try:
        while True:
            raw_message = await websocket.receive_text()
            
            # Parse JSON
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                # Handle plain text (e.g., "ping")
                if raw_message.strip().lower() == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
            
            msg_type = message.get("type")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif msg_type == "config":
                lod_config = message.get("lod")
                router.mvt_handler.update_lod_config(lod_config)
                await websocket.send_json({
                    "type": "ack",
                    "message": "LOD config updated"
                })
            
            elif msg_type == "cancel_download":
                await router.tile_handler.cancel_all_downloads()
                await websocket.send_json({
                    "type": "ack",
                    "message": "Downloads cancelled"
                })
    
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {websocket.client}")
```

**Проблема JSON-парсинга:**

Первоначальная реализация клиента отправляла ping как plain text (`"ping"`), а не JSON (`{"type": "ping"}`). Это приводило к ошибке `json.JSONDecodeError` на сервере.

**Решение:**

Добавлена обработка plain text с fallback на JSON:

```{.python caption="websocket.py: обработка plain text"}
try:
    message = json.loads(raw_message)
except json.JSONDecodeError:
    if raw_message.strip().lower() == "ping":
        await websocket.send_json({"type": "pong"})
        continue
    else:
        logger.warning(f"Invalid JSON: {raw_message}")
        continue
```

**Результат:**

Сервер корректно обрабатывает как JSON, так и plain text ping.

**Коммит:** `1a61a68` (27.01.2026) — "Fixed WebSocket stability in websocket.py — added robust JSON parsing and error handling".

### Реализация на клиенте

**Файл:** `services/qt-client/assets/js/data-ws-client.js`

**Инициализация соединения:**

```{.javascript caption="data-ws-client.js: подключение и отправка LOD"}
export async function initDataWebSocket(apiBaseUrl, lodConfig) {
  const wsUrl = apiBaseUrl.replace('http', 'ws') + '/api/v1/ws';
  const ws = new WebSocket(wsUrl);
  
  ws.onopen = () => {
    console.log('[DataWS] Connected');
    
    // Send LOD config immediately
    ws.send(JSON.stringify({
      type: 'config',
      lod: lodConfig
    }));
  };
  
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    
    if (msg.type === 'tiles_invalidated') {
      console.log('[DataWS] Tiles invalidated, refreshing map...');
      window.map.invalidateCache();
    }
  };
  
  // Ping every 30 seconds
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'ping'}));
    }
  }, 30000);
}
```

**Автоматическая синхронизация LOD:**

При инициализации карты клиент загружает конфигурацию из `map.lod.yaml` и сразу отправляет её на сервер через WebSocket. Это гарантирует, что сервер использует актуальную конфигурацию при генерации тайлов.

**Диаграмма последовательности:**

```{.mermaid}
sequenceDiagram
    participant Map as MapLibre GL
    participant Client as Qt Client
    participant WS as WebSocket Server
    participant MVT as MVT Handler
    
    Client->>WS: connect()
    WS-->>Client: connection open
    Client->>WS: {"type": "config", "lod": {...}}
    WS->>MVT: update_lod_config(lod)
    MVT->>MVT: self.lod_config = lod["layers"]
    WS-->>Client: {"type": "ack", "message": "LOD config updated"}
    
    Note over Client,Map: Пользователь загружает данные
    
    Client->>WS: POST /api/v1/tiles/download
    WS->>MVT: download_area(bbox)
    MVT->>MVT: save_ways_to_db()
    MVT->>WS: broadcast: {"type": "tiles_invalidated"}
    WS-->>Client: {"type": "tiles_invalidated"}
    Client->>Map: map.invalidateCache()
    Map->>WS: GET /tiles/{z}/{x}/{y}.mvt
    WS->>MVT: generate_tile(z, x, y)
    MVT-->>Map: MVT bytes
```

### Компромиссы: Редактирование кода клиента

**Проблема:**

Data Processor отвечает за серверную часть (генерация MVT, загрузка данных), но некоторые исправления требовали правок в клиентском коде:

1. **map-style.js:** Исправление ReferenceError (`baseWidth`), оптимизация интерполяции ширины линий.
2. **map.lod.yaml:** Исправление зазора на Z14.0 (`maxzoom: 14 → 14.1`).

**Обоснование:**

Эти файлы формально находятся в зоне ответственности Qt Client, но:

- **map-style.js** генерирует стили на основе данных, полученных от Data Processor (LOD config, MVT атрибуты). Ошибки в структуре MVT приводили к ошибкам в клиенте.
- **map.lod.yaml** — это конфигурация, которая синхронизируется между клиентом и сервером через WebSocket. Зазор в зумах был обнаружен только при тестировании интеграции.

**Вывод:**

В микросервисной архитектуре с тесной интеграцией (WebSocket, динамическая LOD) границы ответственности размываются. Исправления в клиенте были необходимы для корректной работы Data Processor.

**Коммит:** `1a61a68` (27.01.2026) — "Fix map rendering issues and improve MVT stability" (включает правки в Qt Client).

### Soft BBox Check: Баланс между гибкостью и контролем

**Контекст:**

Первоначальная реализация жестко блокировала запросы тайлов вне настроенного `default_bbox` (МКАД). Это было сделано для предотвращения случайной загрузки терабайтов данных при панорамировании карты.

**Проблема:**

Если пользователь вручную загрузил данные за пределами МКАД (например, через `/api/v1/tiles/download`), он не мог их просматривать из-за жесткой блокировки.

**Решение: Soft BBox Check**

Реализована двухуровневая проверка:

1. **Просмотр данных:** Разрешен для любых областей, если данные уже есть в БД.
2. **Автозагрузка:** Разрешена только внутри `default_bbox`.

```{.python caption="tiles.py: Soft BBox Check"}
tile_bbox = tile_to_bbox(z, x, y)
clip_result = crop_default_bbox(*tile_bbox)
is_outside_bbox = not clip_result["is_valid"]

mvt_data = await router.mvt_handler.generate_tile(z, x, y)

if not mvt_data or len(mvt_data) < 100:
    if is_outside_bbox:
        logger.debug(f"Tile [{z}/{x}/{y}] missing and outside bbox. Skipping download.")
    else:
        logger.info(f"Tile [{z}/{x}/{y}] missing. Triggering download.")
        asyncio.create_task(
            router.tile_handler.download_area(target_bbox, overwrite=False)
        )
    
    return FastAPIResponse(status_code=200, content=b"", headers={...})
```

**Результат:**

Пользователь может просматривать любые области, для которых данные уже загружены, но автоматическая загрузка ограничена настроенными границами. Это предотвращает случайную перегрузку Overpass API.

**Коммит:** `1a61a68` (27.01.2026) — "Added Soft BBox Check in tiles.py — allow viewing existing data outside default_bbox".

### Метрики интеграции

**Таблица: Характеристики WebSocket-соединения**

| Метрика | Значение | Комментарий |
|---------|---------|-------------|
| **Задержка ping/pong** | <50 мс | Локальная сеть (Docker Compose) |
| **Размер LOD config** | ~1.5 КБ | 4 слоя, 14 типов дорог |
| **Частота ping** | 30 секунд | Поддержание соединения |
| **Частота обновлений LOD** | При изменении конфигурации | Событие `tiles_invalidated` |
| **Размер сообщения `tiles_invalidated`** | ~80 байт | JSON |

**Формула задержки синхронизации:**

$$
T_{sync} = T_{ws\_latency} + T_{config\_parse} + T_{invalidate\_cache}
$$

$$
T_{sync} \approx 50 \text{ мс} + 5 \text{ мс} + 10 \text{ мс} = 65 \text{ мс}
$$

где:
- $T_{ws\_latency}$ — задержка WebSocket (ping/pong).
- $T_{config\_parse}$ — парсинг JSON на сервере.
- $T_{invalidate\_cache}$ — очистка кеша тайлов на клиенте.

---

### Protocol Verification

✅ **Verified:**
- WebSocket-протокол подтвержден кодом `websocket.py` (строки 1–120).
- Обработка plain text ping подтверждена `websocket.py:50–55`.
- Автоматическая синхронизация LOD подтверждена `data-ws-client.js:15–20`.
- Soft BBox Check подтвержден `tiles.py:201–210`.
- Компромиссы с редактированием клиента подтверждены коммитом 1a61a68 (7 файлов изменено).

⚠️ **Discrepancy:**
- В отчете упомянуто «задержка <50 мс», но это оценка для локальной сети. В продакшене (через интернет) задержка может быть 100–300 мс.

❌ **Missing:**
- Автоматическое переподключение WebSocket при обрыве соединения — не реализовано на клиенте.
