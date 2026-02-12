## HTTP и WebSocket проксирование

### Реализация HTTP reverse proxy

Функция `reverse_proxy` выполняет перенаправление HTTP-запросов от клиента к upstream-сервису с сохранением метода, заголовков, параметров запроса и тела. Реализация основана на библиотеке `httpx`, которая поддерживает асинхронные запросы и streaming response.

```{.python caption="services/gateway/src/proxy.py (полная версия)"}
import httpx
from fastapi import Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from loguru import logger

async def reverse_proxy(request: Request, path: str, target_url: str, target_path: str, client: httpx.AsyncClient):
    url = f"{target_url}{target_path}"
    
    # Copy query params
    params = dict(request.query_params)
    
    # Copy headers (exclude host to avoid conflicts)
    # Also exclude Hop-by-Hop headers that might conflict with StreamingResponse
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() not in ('host', 'content-length', 'transfer-encoding', 'connection')
    }
    
    logger.trace(f"Proxying {request.method} {request.url} -> {url}")
    
    try:
        # Handle body for non-GET requests
        content = await request.body()
        
        req = client.build_request(
            request.method,
            url,
            headers=headers,
            params=params,
            content=content
        )
        
        r = await client.send(req, stream=True)
            
        # Special handling for 204 No Content (no body allowed, no chunked encoding)
        if r.status_code == 204:
            return Response(
                status_code=204,
                headers=dict(r.headers)
            )

        # Filter response headers
        response_headers = {
            k: v for k, v in r.headers.items()
            if k.lower() not in ('content-length', 'transfer-encoding', 'connection')
        }

        return StreamingResponse(
            r.aiter_raw(),
            status_code=r.status_code,
            headers=response_headers,
            background=None
        )
            
    except httpx.ConnectError:
        logger.error(f"Failed to connect to upstream service: {target_url}")
        raise HTTPException(status_code=503, detail="Upstream service unavailable")
    except Exception as e:
        logger.error(f"Proxy error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Таблица: Этапы обработки HTTP-запроса**

| Этап | Описание | Код |
|------|----------|-----|
| 1. Формирование URL | Конкатенация `target_url` и `target_path` | `url = f"{target_url}{target_path}"` |
| 2. Копирование параметров | Извлечение query params из `request.query_params` | `params = dict(request.query_params)` |
| 3. Фильтрация заголовков | Удаление hop-by-hop заголовков | `if k.lower() not in (...)` |
| 4. Чтение тела запроса | Асинхронное чтение body | `content = await request.body()` |
| 5. Построение запроса | Создание `httpx.Request` | `client.build_request(...)` |
| 6. Отправка запроса | Асинхронная отправка с streaming | `await client.send(req, stream=True)` |
| 7. Обработка ответа | Проверка status code, фильтрация заголовков | `if r.status_code == 204: ...` |
| 8. Возврат ответа | Streaming response клиенту | `StreamingResponse(r.aiter_raw(), ...)` |

### Фильтрация заголовков

**Hop-by-Hop заголовки** — это заголовки, которые относятся к конкретному соединению между клиентом и прокси, а не к end-to-end коммуникации. Их нельзя пересылать дальше:

- `Host`: указывает на целевой хост. При проксировании Gateway заменяет `Host` на адрес upstream-сервиса.
- `Content-Length`: длина тела запроса/ответа. При использовании `StreamingResponse` FastAPI автоматически вычисляет длину или использует chunked encoding.
- `Transfer-Encoding`: метод кодирования (например, `chunked`). Конфликтует с `StreamingResponse`.
- `Connection`: управление соединением (например, `keep-alive`). Не должен пересылаться через прокси.

Фильтрация выполняется через list comprehension:

```{.python caption="Фильтрация заголовков запроса"}
headers = {
    k: v for k, v in request.headers.items() 
    if k.lower() not in ('host', 'content-length', 'transfer-encoding', 'connection')
}
```

Аналогично фильтруются заголовки ответа:

```{.python caption="Фильтрация заголовков ответа"}
response_headers = {
    k: v for k, v in r.headers.items()
    if k.lower() not in ('content-length', 'transfer-encoding', 'connection')
}
```

### Обработка edge-case: HTTP 204 No Content

HTTP-статус `204 No Content` означает, что запрос выполнен успешно, но ответ не содержит тела. Согласно RFC 7231, ответ с кодом 204 **не должен** содержать тело, даже пустое. Использование `StreamingResponse` для 204 приводит к ошибке, так как FastAPI пытается установить `Transfer-Encoding: chunked`, что запрещено для 204.

**Решение:** Специальная обработка 204 через `Response` вместо `StreamingResponse`:

```{.python caption="Обработка HTTP 204"}
if r.status_code == 204:
    return Response(
        status_code=204,
        headers=dict(r.headers)
    )
```

Класс `Response` не устанавливает `Transfer-Encoding` и не пытается отправить тело.

**Таблица: Сравнение Response vs StreamingResponse**

| Критерий | Response | StreamingResponse |
|----------|----------|-------------------|
| Использование | Статический контент, малый размер | Большие файлы, streaming |
| Буферизация | Полная (весь контент в памяти) | Частичная (chunk-by-chunk) |
| Transfer-Encoding | Не устанавливается | `chunked` (если нет Content-Length) |
| Поддержка 204 | Да | Нет (конфликт с chunked) |

### Streaming response

Использование `StreamingResponse` позволяет проксировать большие ответы (например, векторные тайлы размером 100+ КБ) без полной буферизации в памяти Gateway. Это снижает потребление RAM и уменьшает задержку (клиент начинает получать данные сразу, не дожидаясь загрузки всего ответа).

```{.python caption="Streaming response"}
return StreamingResponse(
    r.aiter_raw(),  # Асинхронный итератор по chunk'ам ответа
    status_code=r.status_code,
    headers=response_headers,
    background=None
)
```

**Диаграмма потока данных:**

```{.mermaid}
sequenceDiagram
    participant Client
    participant Gateway
    participant Upstream

    Client->>Gateway: GET /tiles/14/1234/5678
    Gateway->>Upstream: GET /api/v1/tiles/14/1234/5678
    Upstream-->>Gateway: HTTP 200 (chunk 1)
    Gateway-->>Client: HTTP 200 (chunk 1)
    Upstream-->>Gateway: chunk 2
    Gateway-->>Client: chunk 2
    Upstream-->>Gateway: chunk N (final)
    Gateway-->>Client: chunk N (final)
```

### Connection pooling

Gateway использует единый экземпляр `httpx.AsyncClient` для всех запросов. Это обеспечивает переиспользование TCP-соединений (connection pooling) и снижает overhead на установку соединения.

```{.python caption="services/gateway/src/main.py (lifespan management)"}
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Gateway Service")
    # Initialize shared AsyncClient with connection pooling
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    app.state.client = httpx.AsyncClient(limits=limits, timeout=60.0)
    yield
    # Cleanup
    await app.state.client.aclose()
    logger.info("Stopping Gateway Service")
```

**Таблица: Параметры connection pooling**

| Параметр | Значение | Описание |
|----------|----------|----------|
| `max_keepalive_connections` | 20 | Максимальное количество keep-alive соединений в пуле |
| `max_connections` | 100 | Максимальное количество одновременных соединений |
| `timeout` | 60.0 сек | Timeout на выполнение запроса (защита от зависших запросов) |

**Обоснование значений:**
- `max_keepalive_connections=20`: Достаточно для обслуживания 2 upstream-сервисов (Router, Data Processor) при нагрузке ~10 запросов/сек на каждый.
- `max_connections=100`: Защита от исчерпания файловых дескрипторов при burst-нагрузке.
- `timeout=60.0`: Компромисс между защитой от зависших запросов и поддержкой долгих операций (например, построение графа в Router может занимать до 30 сек).

### WebSocket проксирование

WebSocket-соединения используются для real-time уведомлений от Data Processor к клиенту (например, уведомление об обновлении карты). Gateway проксирует WebSocket-соединения через функцию `websocket_proxy`.

```{.python caption="services/gateway/src/ws_proxy.py (полная версия)"}
from fastapi import WebSocket
from loguru import logger
import websockets
from starlette.websockets import WebSocketDisconnect

async def websocket_proxy(client_ws: WebSocket, target_url: str):
    await client_ws.accept()
    logger.info(f"WebSocket proxy started: -> {target_url}")
    
    try:
        async with websockets.connect(target_url) as server_ws:
            # Create tasks for bidirectional communication
            import asyncio
            
            async def forward_to_server():
                try:
                    while True:
                        data = await client_ws.receive_text()
                        await server_ws.send(data)
                except WebSocketDisconnect:
                    logger.info("Client disconnected")
                except Exception as e:
                    logger.error(f"Error forwarding to server: {e}")

            async def forward_to_client():
                try:
                    async for message in server_ws:
                        await client_ws.send_text(message)
                except Exception as e:
                    logger.error(f"Error forwarding to client: {e}")
            
            # Run both tasks
            task1 = asyncio.create_task(forward_to_server())
            task2 = asyncio.create_task(forward_to_client())
            
            done, pending = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                
    except Exception as e:
        logger.error(f"WebSocket proxy error: {e}")
        try:
            await client_ws.close(code=1011)
        except:
            pass
```

**Таблица: Этапы WebSocket-проксирования**

| Этап | Описание | Код |
|------|----------|-----|
| 1. Accept соединения | Принятие WebSocket от клиента | `await client_ws.accept()` |
| 2. Connect к upstream | Установка WebSocket к upstream-сервису | `async with websockets.connect(target_url)` |
| 3. Создание задач | Создание двух asyncio-задач для bidirectional forwarding | `asyncio.create_task(...)` |
| 4. Forward Client→Server | Пересылка сообщений от клиента к серверу | `await server_ws.send(data)` |
| 5. Forward Server→Client | Пересылка сообщений от сервера к клиенту | `await client_ws.send_text(message)` |
| 6. Ожидание завершения | Ожидание завершения любой из задач | `await asyncio.wait(..., FIRST_COMPLETED)` |
| 7. Cleanup | Отмена оставшихся задач | `task.cancel()` |

### Двунаправленная передача (Bidirectional Forwarding)

WebSocket-проксирование требует одновременной пересылки сообщений в обе стороны:
- **Client → Gateway → Upstream:** Клиент отправляет команды (например, подписка на обновления).
- **Upstream → Gateway → Client:** Upstream отправляет уведомления (например, "карта обновлена").

Это реализовано через две параллельные asyncio-задачи:

```{.python caption="Bidirectional forwarding"}
async def forward_to_server():
    while True:
        data = await client_ws.receive_text()  # Ожидание сообщения от клиента
        await server_ws.send(data)             # Пересылка на upstream

async def forward_to_client():
    async for message in server_ws:            # Ожидание сообщений от upstream
        await client_ws.send_text(message)     # Пересылка клиенту
```

Задачи выполняются параллельно через `asyncio.create_task`. Когда одна из задач завершается (например, клиент отключился), вторая задача отменяется через `task.cancel()`.

**Диаграмма WebSocket-потока:**

```{.mermaid}
sequenceDiagram
    participant Client
    participant Gateway
    participant DataProcessor

    Client->>Gateway: WS Handshake /ws/data_updates
    Gateway->>DataProcessor: WS Handshake /ws/data_updates
    DataProcessor-->>Gateway: WS Accept
    Gateway-->>Client: WS Accept
    
    Client->>Gateway: {"action": "subscribe"}
    Gateway->>DataProcessor: {"action": "subscribe"}
    
    DataProcessor-->>Gateway: {"event": "map_updated"}
    Gateway-->>Client: {"event": "map_updated"}
    
    Client->>Gateway: WS Close
    Gateway->>DataProcessor: WS Close
```

### Обработка ошибок

**HTTP-ошибки:**

1. **ConnectError (503 Service Unavailable):** Upstream-сервис недоступен (не запущен, сетевая ошибка).
   ```python
   except httpx.ConnectError:
       raise HTTPException(status_code=503, detail="Upstream service unavailable")
   ```

2. **Generic Exception (500 Internal Server Error):** Любая другая ошибка (например, timeout, неожиданный ответ).
   ```python
   except Exception as e:
       raise HTTPException(status_code=500, detail=str(e))
   ```

**WebSocket-ошибки:**

1. **WebSocketDisconnect:** Клиент закрыл соединение. Логируется как нормальное событие.
   ```python
   except WebSocketDisconnect:
       logger.info("Client disconnected")
   ```

2. **Generic Exception:** Ошибка при пересылке сообщений. Соединение закрывается с кодом 1011 (Internal Error).
   ```python
   except Exception as e:
       await client_ws.close(code=1011)
   ```

**Таблица: HTTP-коды ошибок**

| Код | Причина | Действие клиента |
|-----|---------|------------------|
| 503 | Upstream недоступен | Повторить запрос через 5-10 сек |
| 500 | Ошибка прокси | Проверить логи Gateway |
| 504 | Timeout (60 сек) | Повторить запрос или увеличить timeout |

---

### Protocol Verification

* ✅ **Verified:** 
  - Фильтрация hop-by-hop заголовков (`host`, `content-length`, `transfer-encoding`, `connection`) — подтверждено кодом `proxy.py:14-17, 43-46`.
  - Обработка HTTP 204 через `Response` вместо `StreamingResponse` — подтверждено кодом `proxy.py:36-40`.
  - Bidirectional WebSocket forwarding через две asyncio-задачи — подтверждено кодом `ws_proxy.py:15-42`.
  - Connection pooling через `httpx.AsyncClient` с параметрами `max_keepalive_connections=20, max_connections=100` — подтверждено кодом `main.py:19-20`.

* ⚠️ **Discrepancy:** 
  - Overhead проксирования (5-10 мс HTTP, 2 мс WebSocket) — оценочные значения, не измерены в реальных условиях.

* ❌ **Missing:** 
  - Метрики Prometheus (количество запросов, latency distribution, error rate) — не реализованы.
  - Retry logic при ConnectError — запрос сразу возвращает 503, без попыток переподключения.
