# Архитектурный обзор

## Введение

Клиентское приложение навигационной мультиагентной системы реализовано на основе гибридной архитектуры, объединяющей нативный UI-фреймворк PyQt5 и современный веб-картографический движок MapLibre GL JS. Такой подход позволяет совместить производительность десктопного приложения с гибкостью веб-технологий для визуализации геопространственных данных.

Архитектура построена по принципу разделения ответственности: PyQt5 управляет жизненным циклом приложения, обработкой событий и интеграцией с операционной системой, в то время как MapLibre GL JS обеспечивает рендеринг векторных карт с аппаратным ускорением через WebGL. Взаимодействие между слоями осуществляется через QWebChannel — двунаправленный мост, позволяющий Python-коду вызывать JavaScript-функции и наоборот.

## Обоснование выбора технологий

### Проблема: Требования к картографическому клиенту

Система должна обеспечивать:
- Визуализацию дорожного графа Московской агломерации (200+ тыс. рёбер).
- Интерактивное планирование маршрутов с поддержкой K альтернатив.
- Реактивное обновление векторных тайлов при изменении данных.
- Интеграцию с микросервисной инфраструктурой (Gateway, Router, Data Processor).
- Кроссплатформенность (Linux, Windows, macOS).

### Альтернативы

**Таблица: Сравнение подходов к реализации клиента**

| Подход | Преимущества | Недостатки | Решение |
|--------|-------------|-----------|---------|
| Нативный Qt (QGraphicsView) | Производительность, контроль | Сложность рендеринга векторных тайлов, отсутствие готовых библиотек | ❌ Отклонено |
| Веб-приложение (React + MapLibre) | Гибкость, экосистема | Нет десктопной интеграции, ограничения браузера | ❌ Отклонено |
| PyQt5 + QtWebEngine + MapLibre | Баланс производительности и гибкости | Накладные расходы памяти (Chromium) | ✅ Выбрано |
| Electron + MapLibre | Веб-технологии, кроссплатформенность | Высокое потребление ресурсов, медленный старт | ❌ Отклонено |

### Решение: Гибридная архитектура

Выбран подход PyQt5 + QtWebEngine по следующим причинам:
- **Готовый картографический движок:** MapLibre GL JS поддерживает векторные тайлы (MVT), GPU-рендеринг, динамическую стилизацию.
- **Нативная интеграция:** PyQt5 обеспечивает доступ к системным ресурсам, файловой системе, нативным диалогам.
- **Разделение ответственности:** JavaScript отвечает за карту, Python — за бизнес-логику и API.
- **Экосистема:** Доступ к npm-пакетам для картографии (MapLibre, Turf.js) и Python-библиотекам для работы с данными.

**Компромисс:** QtWebEngine добавляет 200+ МБ накладных расходов памяти (встроенный Chromium), но это приемлемо для десктопного приложения.

## Архитектура системы

### Общая схема

```{.mermaid}
graph TB
    subgraph "Qt Client Application"
        subgraph "Python Layer (PyQt5)"
            Main[main.py<br/>Entry Point]
            MainWindow[MainWindow<br/>UI Controller]
            Handlers[MainWindowHandlers<br/>Event Handlers]
            
            subgraph "API Layer"
                ApiClient[ApiClient<br/>HTTP Client]
                Workers[QThread Workers<br/>GraphFetch, RouteFetch]
                WSClient[DataSocketClient<br/>WebSocket]
            end
            
            subgraph "Bridges (QWebChannel)"
                ConfigBridge[ConfigBridge]
                LoggerBridge[LoggerBridge]
                PointsBridge[PointsBridge]
                ZoomBridge[ZoomBridge]
            end
        end
        
        subgraph "JavaScript Layer (QtWebEngine)"
            MapMain[map-main.js<br/>Initialization]
            MapAPI[MapAPI<br/>Public Interface]
            PointsManager[PointsManager<br/>Route Points]
            AgentAnimator[AgentAnimator<br/>Agent Visualization]
            MapLibre[MapLibre GL JS<br/>Rendering Engine]
        end
    end
    
    subgraph "Backend Services"
        Gateway[Gateway<br/>:8000]
        Router[Router Service]
        DataProc[Data Processor]
    end
    
    Main --> MainWindow
    MainWindow --> Handlers
    MainWindow --> Workers
    MainWindow --> WSClient
    
    Handlers --> ApiClient
    Workers --> Gateway
    WSClient --> Gateway
    
    MainWindow -.QWebChannel.-> ConfigBridge
    MainWindow -.QWebChannel.-> LoggerBridge
    
    ConfigBridge -.Bridge.-> MapMain
    MapMain --> MapAPI
    MapAPI --> PointsManager
    MapAPI --> AgentAnimator
    MapAPI --> MapLibre
    
    PointsManager -.Callbacks.-> PointsBridge
    MapLibre -.Zoom Events.-> ZoomBridge
    
    Gateway --> Router
    Gateway --> DataProc
    
    style Main fill:#3b82f6,color:#fff
    style MapLibre fill:#22c55e,color:#fff
    style Gateway fill:#f59e0b,color:#fff
```

### Разделение ответственности

**Таблица: Компоненты и их роли**

| Слой | Компонент | Ответственность |
|------|-----------|----------------|
| **Python** | `main.py` | Инициализация QApplication, конфигурация окружения |
| | `MainWindow` | Управление UI, setup WebView, HTTP-сервер для assets |
| | `MainWindowHandlers` | Обработка событий (клики, горячие клавиши) |
| | `ApiClient` | HTTP-запросы к Gateway (синхронные и асинхронные) |
| | `QThread Workers` | Асинхронное выполнение блокирующих операций |
| | `DataSocketClient` | WebSocket-подключение для реактивных обновлений |
| | `Bridges` | Передача данных между Python и JavaScript |
| **JavaScript** | `map-main.js` | Инициализация MapLibre, setup QWebChannel |
| | `MapAPI` | Публичный интерфейс для вызовов из Python |
| | `PointsManager` | Управление маркерами точек маршрута |
| | `AgentAnimator` | Анимация движения агентов |
| | `MapLibre GL JS` | Рендеринг векторных тайлов, обработка событий карты |

## Интеграция с микросервисной инфраструктурой

Клиент взаимодействует с бэкендом исключительно через Gateway — единую точку входа, реализующую паттерн API Gateway. Это обеспечивает:
- **Изоляцию:** Клиент не знает о внутренней топологии сервисов.
- **Версионирование:** Gateway может маршрутизировать запросы на разные версии сервисов.
- **Безопасность:** Централизованная аутентификация и авторизация (в планах).

### Схема взаимодействия

```{.mermaid}
sequenceDiagram
    participant Client as Qt Client
    participant Gateway as Gateway :8000
    participant Router as Router Service
    participant DataProc as Data Processor
    
    Note over Client,DataProc: Запрос маршрута
    Client->>Gateway: POST /routing/calculate<br/>{waypoints, k, priority}
    Gateway->>Router: POST /calculate
    Router-->>Gateway: {routes: [...]}
    Gateway-->>Client: {routes: [...]}
    
    Note over Client,DataProc: Загрузка графа
    Client->>Gateway: POST /osm/fetch_road_graph<br/>{bbox}
    Gateway->>DataProc: POST /fetch_road_graph
    DataProc-->>Gateway: NDJSON stream<br/>{type: "progress", ...}
    Gateway-->>Client: NDJSON stream
    DataProc-->>Gateway: {type: "complete", geojson}
    Gateway-->>Client: {type: "complete", geojson}
    
    Note over Client,DataProc: Реактивные обновления
    Client->>Gateway: WS /ws/data_updates
    Gateway->>DataProc: WS /ws/data_updates
    DataProc-->>Gateway: {type: "tile_downloaded", ...}
    Gateway-->>Client: {type: "tile_downloaded", ...}
    Client->>Client: window.app.refreshMVTTiles()
```

### Конфигурация подключения

Адрес Gateway определяется в следующем порядке приоритета:
1. Переменная окружения `GATEWAY_URL`.
2. Файл конфигурации `configs/client/network.yaml`.
3. Значение по умолчанию: `http://localhost:8000`.

```{.yaml caption="configs/client/network.yaml"}
gateway:
  url: "http://localhost:8000"
  timeout: 30
```

Конфигурация загружается через `config_loader` (общий модуль для всех сервисов) и передаётся в конструктор `MainWindow`:

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

## Мост JavaScript-Python через QWebChannel

QWebChannel — механизм Qt для двунаправленной коммуникации между C++/Python и JavaScript в QtWebEngine. Он позволяет:
- **Python → JavaScript:** Вызывать методы JavaScript-объектов из Python.
- **JavaScript → Python:** Вызывать слоты Python-объектов из JavaScript (через сигналы/слоты Qt).

### Архитектура бриджей

Созданы специализированные bridge-объекты для разных типов данных:

**Таблица: QWebChannel Bridges**

| Bridge | Назначение | Методы |
|--------|-----------|--------|
| `ConfigBridge` | Передача конфигурации карты (YAML → JS) | `getMapConfig()` → JSON |
| `LoggerBridge` | Логирование из JavaScript в Python | `log_info(msg)`, `log_error(msg)` |
| `PointsBridge` | Получение координат курсора | `getCursorPosition()` → `{lat, lon}` |
| `ZoomBridge` | Синхронизация зума карты | `setZoom(level)`, `onZoomChanged(level)` |

### Пример: Инъекция конфигурации

Конфигурация карты загружается из YAML и передаётся в JavaScript:

```{.python caption="handlers/config_bridge.py: Инъекция apiBaseUrl"}
@pyqtSlot(result=str)
def getMapConfig(self) -> str:
    """Return map config as JSON string."""
    if self._map_config is None:
        try:
            self._map_config = config_loader.load('client/map.yaml')
        except Exception as e:
            log.error(f"Failed to load map config: {e}")
            self._map_config = {"lod": {"layers": []}, "rendering": {}}
    
    # Inject apiBaseUrl from GUI config
    if 'apiBaseUrl' in self._config:
        self._map_config['apiBaseUrl'] = self._config['apiBaseUrl']
        
    return json.dumps(self._map_config)
```

JavaScript-сторона получает конфигурацию через polling (QWebChannel инициализируется асинхронно):

```{.javascript caption="assets/js/map-config-loader.js"}
export async function loadMapConfig() {
  if (MAP_CONFIG) return MAP_CONFIG;
  if (configLoadPromise) return configLoadPromise;

  configLoadPromise = new Promise((resolve, reject) => {
    const checkChannel = setInterval(() => {
      if (window.globalChannel?.objects?.config_bridge) {
        clearInterval(checkChannel);
        
        window.globalChannel.objects.config_bridge.getMapConfig((jsonStr) => {
          MAP_CONFIG = JSON.parse(jsonStr);
          resolve(MAP_CONFIG);
        });
      }
    }, 50);
  });

  return configLoadPromise;
}
```

### Проблема: Циклические обновления зума

**Контекст:** Пользователь изменяет зум карты колесом мыши.

**Проблема:** Событие `zoomend` в MapLibre вызывает callback в Python, который обновляет слайдер. Слайдер генерирует событие `valueChanged`, которое вызывает `map.setZoom()` в JavaScript, что снова вызывает `zoomend` → бесконечный цикл.

**Решение:** Флаг-семафор `_skipNextZoomUpdate` в `MainWindowHandlers`:

```{.python caption="ui/main_window_handlers.py: Предотвращение циклов"}
def _handle_zoom_from_js(self, zoom_value: int):
    """Handle zoom change from JS (signals/slots ONLY!)."""
    if self._skip_next_zoom_update:
        self._skip_next_zoom_update = False
        return
    
    # Update slider without triggering map update
    self.ui.zoom_control.slider.blockSignals(True)
    self.ui.zoom_control.slider.setValue(zoom_value)
    self.ui.zoom_control.slider.blockSignals(False)

def _set_map_zoom_from_slider(self, position: int):
    """Set map zoom from slider (instant, no animation)."""
    self._skip_next_zoom_update = True  # Prevent feedback loop
    
    js_code = f"window.app.setZoom({position});"
    self.web_view.page().runJavaScript(js_code)
```

## Асинхронная архитектура

Все блокирующие операции (HTTP-запросы, WebSocket) выполняются в отдельных потоках через `QThread`, чтобы не блокировать UI-поток.

### Схема работы QThread Workers

```{.mermaid}
sequenceDiagram
    participant UI as UI Thread<br/>(MainWindow)
    participant Worker as QThread Worker<br/>(RouteFetchWorker)
    participant Gateway as Gateway
    
    UI->>Worker: start() [создание потока]
    activate Worker
    
    Worker->>Gateway: POST /routing/calculate
    Note over Worker: Блокирующий запрос<br/>(requests.post)
    Gateway-->>Worker: {routes: [...]}
    
    Worker->>UI: finished.emit(data) [Qt Signal]
    deactivate Worker
    
    UI->>UI: _on_routes_received(data)
    UI->>UI: Обновление UI
```

### Пример: RouteFetchWorker

```{.python caption="api/api_workers.py: Асинхронный запрос маршрута"}
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

Использование в `MainWindow`:

```{.python caption="ui/main_window_handlers.py: Запуск воркера"}
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

## Конфигурация окружения

### Изоляция от системной темы

Для обеспечения консистентного отображения на разных платформах (KDE, GNOME, Windows) приложение принудительно использует стиль Fusion и кастомную палитру:

```{.python caption="main.py: Изоляция темы"}
os.environ["QT_QPA_PLATFORMTHEME"] = ""  # Disable platform theme
os.environ["QT_STYLE_OVERRIDE"] = "Fusion"

app = QApplication(sys.argv)
app.setStyle("Fusion")

palette = QPalette()
palette.setColor(QPalette.Window, QColor(240, 240, 240))
palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
# ... остальные цвета ...
app.setPalette(palette)
```

### Флаги Chromium для Docker

Для запуска в контейнерах без GPU добавлены флаги:

```{.python caption="main.py: Chromium flags"}
sys.argv.append("--no-sandbox")
sys.argv.append("--ignore-gpu-blocklist")
```

### Отладка WebEngine

Включён remote debugging для инспектирования JavaScript:

```{.python caption="main.py"}
os.environ['QTWEBENGINE_REMOTE_DEBUGGING_PORT'] = '9222'
```

Доступ: `chrome://inspect` → `localhost:9222`.

## Выводы

Гибридная архитектура PyQt5 + MapLibre GL JS обеспечила:
- **Быструю разработку:** Использование готового картографического движка вместо написания рендерера с нуля.
- **Гибкость:** Лёгкая интеграция с веб-экосистемой (npm-пакеты, MapLibre plugins).
- **Разделение ответственности:** Чёткие границы между UI-логикой (Python) и визуализацией (JavaScript).

**Компромиссы:**
- **Память:** QtWebEngine добавляет 200+ МБ (Chromium runtime).
- **Производительность:** Мост QWebChannel добавляет латентность при частых вызовах (например, обновление зума).
- **Сложность отладки:** Ошибки могут возникать как в Python, так и в JavaScript, требуется инспектирование обоих слоёв.

**Альтернативы для будущего:**
- Переход на нативный рендеринг (QGraphicsView + кастомный MVT-парсер) для снижения потребления памяти.
- Использование WebAssembly для критичных по производительности участков JavaScript-кода.

---

## Приложение: Структура файлов

```
services/qt-client/
├── main.py                    # Entry point
├── ui/
│   ├── main_window.py         # MainWindow class
│   ├── main_window_handlers.py # Event handlers
│   ├── main_window_ui.py      # UI setup
│   └── widgets/               # Custom widgets (ZoomControl, PointsPanel, etc.)
├── api/
│   ├── client.py              # ApiClient (HTTP)
│   ├── api_workers.py         # QThread workers
│   └── ws_client.py           # WebSocket client
├── handlers/
│   ├── config_bridge.py       # Config bridge
│   ├── logger_bridge.py       # Logger bridge
│   ├── points_bridge.py       # Points bridge
│   └── zoom_bridge.py         # Zoom bridge
├── assets/
│   ├── map.html               # HTML container for MapLibre
│   └── js/
│       ├── map-main.js        # Initialization
│       ├── map-api.js         # Public API
│       ├── points-manager.js  # Points management
│       ├── agent-animator.js  # Agent animation
│       └── ...
├── requirements.txt
└── Makefile
```
