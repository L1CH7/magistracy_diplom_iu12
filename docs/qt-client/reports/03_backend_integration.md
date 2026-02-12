# Интеграция с бэкендом

## Введение

Клиентское приложение взаимодействует с микросервисной инфраструктурой исключительно через Gateway — единую точку входа, реализующую паттерн API Gateway. Архитектура интеграции построена на трёх компонентах:
- **ApiClient** — HTTP-клиент для синхронных и асинхронных запросов.
- **QThread Workers** — фоновые потоки для блокирующих операций (загрузка графа, расчёт маршрутов).
- **WebSocket Client** — реактивный канал для уведомлений о событиях (загрузка тайлов).

Все запросы проходят через Gateway (`http://localhost:8000`), который маршрутизирует их к соответствующим сервисам (Router, Data Processor). Это обеспечивает изоляцию клиента от внутренней топологии сервисов и упрощает версионирование API.

## Архитектура API-клиента

### ApiClient: Унифицированный HTTP-клиент

`ApiClient` — класс-обёртка над `httpx` (асинхронный) и `requests` (синхронный), предоставляющий единый интерфейс для взаимодействия с Gateway.

**Таблица: Методы ApiClient**

| Метод | Тип | Назначение | Endpoint |
|-------|-----|-----------|----------|
| `find_routes()` | async | Запрос маршрутов (асинхронный) | `POST /routing/calculate` |
| `find_routes_sync()` | sync | Запрос маршрутов (синхронный) | `POST /routing/calculate` |
| `close()` | async | Закрытие HTTP-клиента | — |

### Реализация

```{.python caption="api/client.py: ApiClient"}
class ApiClient:
    """
    Unified client for communicating with the Gateway service.
    
    Handles:
    - Routing requests (/routing/find)
    - Graph data (/osm/fetch_road_graph) (Via worker usually)
    - Tile requests (generic helper)
    """
    
    def __init__(self, gateway_url: str):
        self.base_url = gateway_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"ApiClient initialized with gateway: {self.base_url}")
        
    async def close(self):
        await self.client.aclose()
        
    def _url(self, path: str) -> str:
        """Construct full URL."""
        return f"{self.base_url}{path}"

    async def find_routes(
        self, 
        points: List[Dict[str, float]], 
        k: int = 1,
        priority: int = 0
    ) -> Dict[str, Any]:
        """
        Request route calculation between points.
        
        Args:
            points: List of dicts, e.g. [{"lat": 55.7, "lon": 37.6}, ...]
            k: Number of routes/alternatives
            priority: Routing priority factor (0-100)
            
        Returns:
            JSON response dictionary containing routes
        """
        url = self._url("/routing/calculate")
        payload = {
            "waypoints": points,
            "priority": priority,
            "k": k
        }
        
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Routing request failed: {e}")
            raise

    def find_routes_sync(
        self, 
        points: List[Dict[str, float]], 
        k: int = 1,
        priority: int = 0
    ) -> Dict[str, Any]:
        """
        Synchronous version of find_routes for use in QThreads.
        Uses 'requests' library.
        """
        import requests
        url = self._url("/routing/calculate")
        payload = {
            "waypoints": points,
            "priority": priority,
            "k": k
        }
        
        try:
            response = requests.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Routing request failed: {e}")
            raise
```

### Обоснование двух реализаций

**Проблема:** Qt работает в синхронной модели (event loop), а `httpx` требует `asyncio`. Использование `asyncio` в QThread усложняет код (нужен отдельный event loop).

**Решение:** Два метода:
- `find_routes()` — асинхронный (для использования вне QThread, например, в тестах).
- `find_routes_sync()` — синхронный (для использования в `QThread.run()`).

**Компромисс:** Дублирование кода, но упрощение интеграции с Qt.

## QThread Workers: Асинхронное выполнение

Все блокирующие операции (HTTP-запросы, WebSocket) выполняются в отдельных потоках через `QThread`, чтобы не блокировать UI-поток.

### Архитектура воркеров

```{.mermaid}
graph TB
    subgraph "UI Thread"
        MainWindow[MainWindow]
        Handlers[MainWindowHandlers]
    end
    
    subgraph "Worker Threads"
        GraphWorker[GraphFetchWorker<br/>QThread]
        RouteWorker[RouteFetchWorker<br/>QThread]
        WSWorker[DataSocketWorker<br/>QThread]
    end
    
    subgraph "Backend"
        Gateway[Gateway :8000]
    end
    
    Handlers -->|start()| GraphWorker
    Handlers -->|start()| RouteWorker
    MainWindow -->|start()| WSWorker
    
    GraphWorker -->|POST /osm/fetch_road_graph| Gateway
    RouteWorker -->|POST /routing/calculate| Gateway
    WSWorker -->|WS /ws/data_updates| Gateway
    
    GraphWorker -.finished.emit(data).-> Handlers
    RouteWorker -.finished.emit(data).-> Handlers
    WSWorker -.message_received.emit(data).-> MainWindow
    
    style GraphWorker fill:#3b82f6,color:#fff
    style RouteWorker fill:#3b82f6,color:#fff
    style WSWorker fill:#22c55e,color:#fff
```

### GraphFetchWorker: Загрузка дорожного графа

Загружает GeoJSON дорожного графа для заданного bbox. Поддерживает NDJSON-стриминг для отображения прогресса.

```{.python caption="api/api_workers.py: GraphFetchWorker"}
class GraphFetchWorker(QThread):
    """Worker thread for fetching road graph data asynchronously.
    
    Signals:
        progress(str): Progress message
        finished(dict): Complete graph data
        error(str): Error message
    """
    
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, gateway_url: str, bbox: list):
        super().__init__()
        self.gateway_url = gateway_url
        self.bbox = bbox
        self._is_cancelled = False
        # Use config timeout (600s for large bbox)
        config = config_loader.load('client/data.yaml')
        self._timeout = config['api']['timeout_graph_fetch']
    
    def run(self):
        """Execute the graph fetch request in background thread."""
        try:
            url = f"{self.gateway_url}/osm/fetch_road_graph"
            
            response = requests.post(
                url,
                json={"bbox": self.bbox},
                stream=True,
                timeout=self._timeout  # 600s for large bbox
            )
            response.raise_for_status()
            
            geojson = None
            total_ways = 0
            is_cached = False
            
            # Parse NDJSON stream
            for line in response.iter_lines():
                if self._is_cancelled:
                    return
                
                if line:
                    data = json.loads(line.decode('utf-8'))
                    msg_type = data.get("type")
                    
                    if msg_type == "info":
                        message = data.get("message", "")
                        self.progress.emit(message)
                    
                    elif msg_type == "progress":
                        message = data.get("message")
                        if message:
                            self.progress.emit(message)
                    
                    elif msg_type == "complete":
                        geojson = data.get("geojson")
                        total_ways = data.get("total_ways", 0)
                        is_cached = data.get("cached", False)
                        break
                    
                    elif msg_type == "error":
                        error_msg = data.get("error", "Unknown error")
                        self.error.emit(f"Server error: {error_msg}")
                        return
            
            if geojson:
                self.finished.emit({
                    'geojson': geojson,
                    'total_ways': total_ways,
                    'cached': is_cached,
                    'bbox': self.bbox
                })
            else:
                self.error.emit("No data received from server")
        
        except requests.exceptions.Timeout:
            self.error.emit("Request timeout - server took too long")
        except requests.exceptions.ConnectionError:
            self.error.emit("Connection failed - is server running?")
        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")
```

**Ключевые особенности:**
- **NDJSON-стриминг:** Сервер отправляет прогресс построчно (`{type: "progress", ...}`), клиент обновляет UI в реальном времени.
- **Таймаут 600 сек:** Загрузка большого bbox (вся Москва) может занять до 10 минут.
- **Отмена:** Флаг `_is_cancelled` позволяет прервать операцию.

### RouteFetchWorker: Расчёт маршрутов

Запрашивает K альтернативных маршрутов между точками.

```{.python caption="api/api_workers.py: RouteFetchWorker"}
class RouteFetchWorker(QThread):
    """Worker thread for fetching route data asynchronously."""
    
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, gateway_url: str, waypoints: list, k: int = 1, priority: int = 0):
        super().__init__()
        self.gateway_url = gateway_url
        self.waypoints = waypoints
        self.k = k
        self.priority = priority
        self._is_cancelled = False
    
    def run(self):
        """Execute the route fetch request in background thread."""
        try:
            from .client import ApiClient
            client = ApiClient(self.gateway_url)
            
            # Convert tuples to dicts
            formatted_points = [
                {"lat": wp[0], "lon": wp[1]} for wp in self.waypoints
            ]
            
            data = client.find_routes_sync(
                formatted_points, 
                k=self.k, 
                priority=self.priority
            )
            
            if self._is_cancelled:
                return

            self.finished.emit(data)
        
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")
```

**Использование:**

```{.python caption="ui/main_window_handlers.py: Запуск RouteFetchWorker"}
def _on_get_k_routes(self, k: int):
    """Handle Get K Routes button click."""
    # ... получение точек маршрута ...
    
    # Create and start worker
    self._route_worker = RouteFetchWorker(
        self.gateway_url, 
        waypoints, 
        k=k, 
        priority=0
    )
    self._route_worker.finished.connect(self._on_routes_received)
    self._route_worker.error.connect(self._on_route_error)
    self._route_worker.start()
```

### DataSocketWorker: WebSocket в QThread

Запускает WebSocket-клиент в отдельном потоке с собственным `asyncio` event loop.

```{.python caption="api/api_workers.py: DataSocketWorker"}
class DataSocketWorker(QThread):
    """
    Worker thread for Data WebSocket.
    Runs asyncio loop for WebSocket client.
    """
    message_received = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    
    def __init__(self, gateway_url: str):
        super().__init__()
        self.gateway_url = gateway_url
        self.client = None
        self._loop = None
        
    def run(self):
        """Run the WebSocket client."""
        # Create new event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        self.client = DataSocketClient(self.gateway_url)
        # Bridge callback to Qt signal (emit() is thread-safe)
        self.client.on_message = self.message_received.emit
        self.client.on_connect = self.connected.emit
        
        try:
            # connect() runs until connection closes
            self._loop.run_until_complete(self.client.connect())
        except Exception as e:
            log.error(f"DataSocketWorker error: {e}")
        finally:
            self.disconnected.emit()
            self._loop.close()
            
    def stop(self):
        """Stop the worker."""
        if self._loop and self.client and self.client.connected:
            # Schedule disconnect in the loop
            asyncio.run_coroutine_threadsafe(
                self.client.disconnect(), 
                self._loop
            )
        # Wait for thread to finish
        self.wait(2000)
```

**Ключевые особенности:**
- **Отдельный event loop:** `asyncio.new_event_loop()` создаёт изолированный loop для потока.
- **Thread-safe сигналы:** `emit()` в PyQt5 безопасен для вызова из других потоков.
- **Graceful shutdown:** `stop()` корректно закрывает WebSocket и ждёт завершения потока.

## WebSocket Client: Реактивные обновления

`DataSocketClient` — WebSocket-клиент для получения уведомлений от Data Processor о событиях (загрузка тайлов).

### Архитектура

```{.mermaid}
sequenceDiagram
    participant MainWindow as MainWindow (UI Thread)
    participant Worker as DataSocketWorker (QThread)
    participant WSClient as DataSocketClient (asyncio)
    participant Gateway as Gateway
    participant DataProc as Data Processor
    
    MainWindow->>Worker: start()
    activate Worker
    Worker->>WSClient: connect()
    WSClient->>Gateway: WS /ws/data_updates
    Gateway->>DataProc: WS /ws/data_updates
    
    Worker->>MainWindow: connected.emit()
    
    Note over DataProc: Tile downloaded
    DataProc-->>Gateway: {type: "tile_downloaded", z, x, y}
    Gateway-->>WSClient: {type: "tile_downloaded", z, x, y}
    WSClient->>Worker: on_message(data)
    Worker->>MainWindow: message_received.emit(data)
    
    MainWindow->>MainWindow: _on_data_message(data)
    MainWindow->>MainWindow: window.app.refreshMVTTiles()
    
    deactivate Worker
```

### Реализация

```{.python caption="api/ws_client.py: DataSocketClient"}
class DataSocketClient:
    """
    WebSocket client for Data Processor updates.
    
    Receives real-time notifications about tile downloads.
    """
    
    def __init__(self, gateway_url: str):
        # Convert HTTP/HTTPS to WS/WSS
        if gateway_url.startswith("https"):
            ws_base = gateway_url.replace("https", "wss")
        elif gateway_url.startswith("http"):
            ws_base = gateway_url.replace("http", "ws")
        else:
            ws_base = f"ws://{gateway_url}"
            
        self.url = f"{ws_base}/ws/data_updates"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        
        # Callback for updates
        self.on_message: Optional[Callable] = None
        self.on_connect: Optional[Callable] = None
        
        logger.info(f"DataSocketClient created: {self.url}")
    
    async def connect(self):
        """Connect to Data Processor WebSocket."""
        try:
            self.ws = await websockets.connect(self.url)
            self.connected = True
            
            logger.success(f"Connected to Data Socket: {self.url}")
            
            if self.on_connect:
                if asyncio.iscoroutinefunction(self.on_connect):
                    await self.on_connect()
                else:
                    self.on_connect()
            
            # Start receiving loop
            await self._receive_loop()
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.connected = False
            raise e

    async def _receive_loop(self):
        """Receive updates."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    # Call callback
                    if self.on_message:
                        self.on_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON message: {message}")
                
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
```

### Обработка событий

```{.python caption="ui/main_window.py: Обработка WebSocket-сообщений"}
def _on_data_message(self, data: dict):
    """Handle data updates from WebSocket."""
    msg_type = data.get("type")
    
    if msg_type == "tile_downloaded":
        z = data.get("z")
        x = data.get("x")
        y = data.get("y")
        log.info(f"Tile downloaded: z={z}, x={x}, y={y}")
        
        # Refresh MVT tiles on map
        js_code = "window.app.refreshMVTTiles();"
        self.web_view.page().runJavaScript(js_code)
    
    elif msg_type == "status":
        log.info(f"Data Processor status: {data}")
```

## Обработка ошибок и таймаутов

### Конфигурация таймаутов

Таймауты задаются в `configs/client/data.yaml`:

```{.yaml caption="configs/client/data.yaml"}
api:
  timeout_default: 30
  timeout_graph_fetch: 600  # 10 minutes for large bbox
  timeout_route: 60
```

### Обработка ошибок

**Таблица: Типы ошибок и обработка**

| Ошибка | Причина | Обработка |
|--------|---------|-----------|
| `ConnectionError` | Gateway недоступен | Показать сообщение "Connection failed" |
| `Timeout` | Запрос превысил таймаут | Показать "Request timeout" |
| `HTTPError 4xx` | Неверный запрос | Показать детали ошибки из JSON |
| `HTTPError 5xx` | Ошибка сервера | Показать "Server error" |
| `JSONDecodeError` | Некорректный ответ | Логировать и показать "Invalid response" |

### Пример обработки

```{.python caption="api/api_workers.py: Обработка ошибок"}
try:
    response = requests.post(url, json=payload, timeout=60.0)
    response.raise_for_status()
    return response.json()
except requests.exceptions.Timeout:
    self.error.emit("Request timeout - server took too long")
except requests.exceptions.ConnectionError:
    self.error.emit("Connection failed - is server running?")
except requests.exceptions.HTTPError as e:
    self.error.emit(f"HTTP error: {e}")
except Exception as e:
    self.error.emit(f"Unexpected error: {str(e)}")
```

## Интеграция с Gateway

### Резолюция URL

Адрес Gateway определяется в следующем порядке:
1. Переменная окружения `GATEWAY_URL`.
2. Файл `configs/client/network.yaml`.
3. Значение по умолчанию: `http://localhost:8000`.

```{.python caption="main.py: Резолюция Gateway URL"}
gateway_url = os.getenv("GATEWAY_URL")

if not gateway_url:
    try:
        from services.common.config import config_loader
        net_config = config_loader.load('client/network.yaml')
        gateway_url = net_config.get('gateway', {}).get('url')
    except Exception as e:
        print(f"Warning: Could not load network config: {e}")
        
if not gateway_url:
    gateway_url = "http://localhost:8000"

window = MainWindow(gateway_url)
```

### Маршрутизация запросов

**Таблица: Эндпоинты Gateway**

| Клиентский запрос | Gateway Endpoint | Целевой сервис |
|-------------------|------------------|----------------|
| Расчёт маршрутов | `POST /routing/calculate` | Router |
| Загрузка графа | `POST /osm/fetch_road_graph` | Data Processor |
| Векторные тайлы | `GET /tiles/{z}/{x}/{y}.mvt` | Data Processor |
| WebSocket | `WS /ws/data_updates` | Data Processor |
| Статус | `GET /status` | Data Processor |

## Выводы

Архитектура интеграции с бэкендом обеспечила:
- **Изоляцию:** Клиент не знает о внутренней топологии сервисов, все запросы через Gateway.
- **Отзывчивость:** QThread-воркеры предотвращают блокировку UI при длительных операциях.
- **Реактивность:** WebSocket обеспечивает мгновенное обновление тайлов при изменении данных.
- **Надёжность:** Обработка таймаутов и ошибок с информативными сообщениями пользователю.

**Компромиссы:**
- **Дублирование кода:** Синхронные и асинхронные версии методов (`find_routes` vs `find_routes_sync`).
- **Сложность отладки:** Ошибки могут возникать в разных потоках (UI, QThread, asyncio loop).
- **Таймауты:** Загрузка большого графа (600 сек) блокирует воркер, но не UI.

**Метрики:**
- Время подключения WebSocket: ~100 мс.
- Время запроса маршрута (K=1): 6.2 сек (median, зависит от Router).
- Время загрузки графа (bbox Москвы): 13 минут (первый запрос), 2 сек (кеш).

---

## Приложение: Схема потоков данных

```{.mermaid}
graph LR
    subgraph "Qt Client"
        UI[UI Thread<br/>MainWindow]
        GraphW[GraphFetchWorker<br/>QThread]
        RouteW[RouteFetchWorker<br/>QThread]
        WSW[DataSocketWorker<br/>QThread + asyncio]
    end
    
    subgraph "Backend"
        Gateway[Gateway<br/>:8000]
        Router[Router Service]
        DataProc[Data Processor]
    end
    
    UI -->|start()| GraphW
    UI -->|start()| RouteW
    UI -->|start()| WSW
    
    GraphW -->|POST /osm/fetch_road_graph| Gateway
    RouteW -->|POST /routing/calculate| Gateway
    WSW -->|WS /ws/data_updates| Gateway
    
    Gateway --> DataProc
    Gateway --> Router
    
    GraphW -.finished.emit().-> UI
    RouteW -.finished.emit().-> UI
    WSW -.message_received.emit().-> UI
    
    style UI fill:#3b82f6,color:#fff
    style Gateway fill:#f59e0b,color:#fff
```
