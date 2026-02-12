# Мост JavaScript-Python

## Введение

QWebChannel — механизм Qt для двунаправленной коммуникации между Python и JavaScript в QtWebEngine. Он позволяет:
- **Python → JavaScript:** Вызывать методы JavaScript через `runJavaScript()`.
- **JavaScript → Python:** Вызывать слоты Python-объектов через сигналы/слоты Qt.

Архитектура моста построена на специализированных bridge-объектах, каждый из которых отвечает за передачу определённого типа данных (конфигурация, логи, координаты, зум).

## Архитектура бриджей

### Схема взаимодействия

```{.mermaid}
sequenceDiagram
    participant Python as Python<br/>(MainWindow)
    participant QWebChannel as QWebChannel
    participant JS as JavaScript<br/>(map-main.js)
    
    Note over Python,JS: Инициализация
    Python->>QWebChannel: Регистрация бриджей
    QWebChannel->>JS: Экспонирование объектов
    JS->>QWebChannel: Polling (setInterval)
    QWebChannel->>JS: Готовность канала
    
    Note over Python,JS: Python → JavaScript
    Python->>Python: runJavaScript("window.app.setZoom(12)")
    Python->>JS: Вызов метода
    JS->>JS: Выполнение
    
    Note over Python,JS: JavaScript → Python
    JS->>QWebChannel: zoom_bridge.onZoomChanged(14)
    QWebChannel->>Python: Вызов слота
    Python->>Python: _handle_zoom_from_js(14)
```

### Таблица бриджей

**Таблица: QWebChannel Bridges**

| Bridge | Файл | Назначение | Методы |
|--------|------|-----------|--------|
| `ConfigBridge` | `handlers/config_bridge.py` | Передача конфигурации YAML → JSON | `getMapConfig()` |
| `LoggerBridge` | `handlers/logger_bridge.py` | Логирование из JavaScript | `log_info()`, `log_error()` |
| `PointsBridge` | `handlers/points_bridge.py` | Получение координат курсора | `getCursorPosition()` |
| `ZoomBridge` | `handlers/zoom_bridge.py` | Синхронизация зума | `setZoom()`, `onZoomChanged()` |

## ConfigBridge: Передача конфигурации

### Проблема

Конфигурация карты (LOD, стили, анимация) хранится в YAML-файлах. JavaScript-код должен получить доступ к этой конфигурации для генерации MapLibre Style Spec.

### Решение

`ConfigBridge` загружает YAML через `config_loader` и возвращает JSON-строку.

```{.python caption="handlers/config_bridge.py"}
class ConfigBridge(QObject):
    """Bridge for accessing Python config from JavaScript."""

    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        self._map_config = None  # Lazy load

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

### JavaScript-сторона

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
    }, 50);  // Poll every 50ms
  });

  return configLoadPromise;
}
```

**Примечание:** Polling необходим, так как QWebChannel инициализируется асинхронно. Альтернатива — событие `qwebChannelReady`, но оно не всегда надёжно.

## ZoomBridge: Синхронизация зума

### Проблема: Циклические обновления

**Сценарий:**
1. Пользователь изменяет зум колесом мыши.
2. MapLibre генерирует событие `zoomend`.
3. JavaScript вызывает `zoom_bridge.onZoomChanged(14)`.
4. Python обновляет слайдер: `slider.setValue(14)`.
5. Слайдер генерирует `valueChanged(14)`.
6. Python вызывает `map.setZoom(14)`.
7. MapLibre генерирует `zoomend` → **цикл**.

### Решение: Флаг-семафор

```{.python caption="ui/main_window_handlers.py"}
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

**Альтернатива:** `blockSignals()` блокирует все сигналы виджета, но это менее гибко, чем флаг.

## LoggerBridge: Логирование из JavaScript

### Назначение

Перенаправление логов из JavaScript в Python-логгер (loguru) для централизованного логирования.

```{.python caption="handlers/logger_bridge.py"}
class LoggerBridge(QObject):
    """Bridge for logging from JavaScript to Python."""

    @pyqtSlot(str)
    def log_info(self, message: str):
        """Log info message from JavaScript."""
        log.info(f"[JS] {message}")

    @pyqtSlot(str)
    def log_error(self, message: str):
        """Log error message from JavaScript."""
        log.error(f"[JS] {message}")
```

### JavaScript-сторона

```{.javascript caption="assets/js/map-main.js"}
function logToPython(message) {
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    console.log(message);  // Fallback
  }
}

logToPython('[MAP] Initialized, marking as loaded');
```

## PointsBridge: Получение координат курсора

### Назначение

Получение координат курсора для установки точек маршрута через горячие клавиши (Ctrl+1/2/3).

```{.python caption="handlers/points_bridge.py"}
class PointsBridge(QObject):
    """Bridge for getting cursor position from map."""

    @pyqtSlot(result=str)
    def getCursorPosition(self) -> str:
        """Get current cursor position as JSON."""
        # This is called from Python, but we need to get data from JS
        # So we return empty and use callback in JS
        return "{}"
```

**Примечание:** Этот бридж не используется напрямую. Вместо этого Python вызывает JavaScript-метод `window.app.getCursorPosition()` через `runJavaScript()` с callback.

### Использование

```{.python caption="ui/main_window_handlers.py"}
def _on_ctrl_1(self):
    """Ctrl+1: Set From point at cursor position."""
    js_code = "window.app.getCursorPosition();"
    
    def callback(result):
        if result and 'lat' in result and 'lon' in result:
            log.info(f"Setting From point: {result}")
            
            js_set = f"window.app.setStart({result});"
            self.web_view.page().runJavaScript(js_set)
            
            self._update_selected_points()
        else:
            log.warning("No cursor position available")
    
    self.web_view.page().runJavaScript(js_code, callback)
```

## Инициализация QWebChannel

### Python-сторона

```{.python caption="ui/main_window.py"}
def _setup_js_callbacks(self):
    """Setup JavaScript callbacks for event-based updates."""
    
    # Create channel
    self.channel = QWebChannel()
    
    # Register bridges
    self.channel.registerObject("config_bridge", self.config_bridge)
    self.channel.registerObject("logger_bridge", self.logger_bridge)
    self.channel.registerObject("zoom_bridge", self.zoom_bridge)
    
    # Set channel on page
    self.web_view.page().setWebChannel(self.channel)
    
    log.info("QWebChannel initialized and bridges registered")
```

### JavaScript-сторона

```{.javascript caption="assets/js/map-main.js"}
// Wait for QWebChannel to be ready
new QWebChannel(qt.webChannelTransport, function(channel) {
  window.globalChannel = channel;
  
  // Access bridges
  const config_bridge = channel.objects.config_bridge;
  const logger_bridge = channel.objects.logger_bridge;
  const zoom_bridge = channel.objects.zoom_bridge;
  
  logger_bridge.log_info('[QWebChannel] Ready');
  
  // Connect zoom events
  window.map.on('zoomend', () => {
    const zoom = Math.round(window.map.getZoom());
    zoom_bridge.onZoomChanged(zoom);
  });
});
```

## Проблемы и решения

### Проблема: Асинхронная инициализация

**Контекст:** Python регистрирует бриджи синхронно, но JavaScript получает доступ к ним асинхронно (после загрузки `qwebchannel.js`).

**Решение:** Polling через `setInterval()` до готовности канала.

### Проблема: Сериализация данных

**Контекст:** QWebChannel передаёт только примитивные типы (string, number, boolean). Сложные объекты требуют сериализации.

**Решение:** JSON-сериализация в Python, десериализация в JavaScript.

```{.python caption="handlers/config_bridge.py"}
return json.dumps(self._map_config)
```

```{.javascript caption="assets/js/map-config-loader.js"}
MAP_CONFIG = JSON.parse(jsonStr);
```

### Проблема: Латентность

**Контекст:** Вызов JavaScript-метода через `runJavaScript()` добавляет латентность (~10-50 мс).

**Решение:** Минимизировать частоту вызовов. Например, обновление зума происходит только при отпускании слайдера, а не при каждом движении.

## Выводы

QWebChannel обеспечил:
- **Двунаправленную коммуникацию:** Python ↔ JavaScript без HTTP-запросов.
- **Типобезопасность:** Сигналы/слоты Qt гарантируют корректность типов.
- **Изоляцию:** Каждый бридж отвечает за свой тип данных (SRP).

**Компромиссы:**
- **Латентность:** Вызовы через QWebChannel медленнее прямых вызовов функций.
- **Сложность отладки:** Ошибки могут возникать как в Python, так и в JavaScript.
- **Асинхронность:** Требуется polling для определения готовности канала.

**Метрики:**
- Время инициализации QWebChannel: ~100 мс.
- Латентность вызова `runJavaScript()`: 10-50 мс.
- Размер конфигурации (JSON): ~5 КБ.

---

## Приложение: Схема бриджей

```{.mermaid}
graph TB
    subgraph "Python (MainWindow)"
        ConfigBridge[ConfigBridge<br/>getMapConfig]
        LoggerBridge[LoggerBridge<br/>log_info, log_error]
        ZoomBridge[ZoomBridge<br/>onZoomChanged]
    end
    
    subgraph "QWebChannel"
        Channel[QWebChannel<br/>Transport Layer]
    end
    
    subgraph "JavaScript (map-main.js)"
        ConfigLoader[map-config-loader.js<br/>loadMapConfig]
        Logger[logToPython<br/>Helper]
        ZoomHandler[Zoom Event Handler]
    end
    
    ConfigBridge --> Channel
    LoggerBridge --> Channel
    ZoomBridge --> Channel
    
    Channel --> ConfigLoader
    Channel --> Logger
    Channel --> ZoomHandler
    
    style Channel fill:#f59e0b,color:#fff
```
