# Картографический движок

## Введение

Визуализация карты реализована на базе MapLibre GL JS — открытого форка Mapbox GL JS, обеспечивающего векторный рендеринг с аппаратным ускорением через WebGL. Движок поддерживает векторные тайлы формата MVT (Mapbox Vector Tiles), динамическую стилизацию, плавные анимации и интерактивные элементы.

Архитектура JavaScript-слоя построена по модульному принципу (ES6 modules) с чётким разделением ответственности: инициализация карты, управление состоянием точек маршрута, анимация агентов, генерация стилей. Все модули взаимодействуют через публичный API (`MapAPI`), который экспонируется в глобальную область видимости для вызовов из Python.

## MapLibre GL JS: Выбор и обоснование

### Требования к картографическому движку

- **Векторные тайлы:** Поддержка формата MVT для эффективной передачи геометрии (в 5-10 раз меньше GeoJSON).
- **GPU-рендеринг:** Использование WebGL для отрисовки десятков тысяч объектов без деградации производительности.
- **Динамическая стилизация:** Возможность изменения цветов, ширины линий, фильтров без перезагрузки данных.
- **Открытый исходный код:** Отсутствие vendor lock-in, возможность кастомизации.

### Альтернативы

**Таблица: Сравнение картографических библиотек**

| Библиотека | Векторные тайлы | GPU-рендеринг | Лицензия | Решение |
|------------|----------------|---------------|----------|---------|
| Leaflet | ❌ (только растр) | ❌ | BSD | ❌ Не подходит |
| OpenLayers | ✅ (через плагины) | ⚠️ (частично) | BSD | ❌ Сложная интеграция |
| Mapbox GL JS | ✅ | ✅ | Proprietary (v2+) | ❌ Проприетарная лицензия |
| MapLibre GL JS | ✅ | ✅ | BSD-3-Clause | ✅ Выбрано |

**Решение:** MapLibre GL JS выбран как открытая альтернатива Mapbox GL JS с полной совместимостью API и активным сообществом.

## Архитектура JavaScript-модулей

Код организован в виде ES6-модулей с явными зависимостями через `import/export`. Это обеспечивает:
- **Изоляцию:** Каждый модуль имеет собственную область видимости.
- **Тестируемость:** Модули можно тестировать независимо.
- **Читаемость:** Явные зависимости вместо глобальных переменных.

### Схема модулей

```{.mermaid}
graph LR
    subgraph "Entry Point"
        HTML[map.html]
    end
    
    subgraph "Core Modules"
        MapMain[map-main.js<br/>Initialization]
        MapAPI[map-api.js<br/>Public API]
        MapConfig[map-config-loader.js<br/>Config Loader]
        MapStyle[map-style.js<br/>Style Generator]
    end
    
    subgraph "Feature Modules"
        Points[points-manager.js<br/>Route Points]
        Agent[agent-animator.js<br/>Agent Animation]
        Markers[markers.js<br/>Marker Factory]
        MVTRefresh[mvt-refresh.js<br/>Tile Refresh]
        DebugGrid[debug-grid.js<br/>Debug Overlay]
    end
    
    subgraph "Integration"
        DataWS[data-ws-client.js<br/>WebSocket Client]
    end
    
    HTML --> MapMain
    MapMain --> MapConfig
    MapMain --> MapStyle
    MapMain --> MapAPI
    MapMain --> Points
    MapMain --> Agent
    MapMain --> DataWS
    
    MapAPI --> Points
    MapAPI --> Agent
    MapAPI --> MVTRefresh
    
    Points --> Markers
    Agent --> Markers
    Agent --> MapConfig
    
    MapStyle --> MapConfig
    
    style MapMain fill:#3b82f6,color:#fff
    style MapAPI fill:#22c55e,color:#fff
    style MapLibre fill:#f59e0b,color:#fff
```

**Таблица: Назначение модулей**

| Модуль | Ответственность | Экспорты |
|--------|----------------|----------|
| `map-main.js` | Инициализация MapLibre, setup QWebChannel | `initializeMap()` |
| `map-api.js` | Публичный API для Python (window.app) | `class MapAPI` |
| `map-config-loader.js` | Загрузка конфигурации из Python | `loadMapConfig()`, `getMapConfig()` |
| `map-style.js` | Генерация MapLibre Style Spec | `createMapStyle()` |
| `points-manager.js` | Управление точками маршрута (From/Via/To) | `class PointsManager` |
| `agent-animator.js` | Плавная анимация движения агента | `class AgentAnimator` |
| `markers.js` | Фабрика HTML-маркеров | `createMarkerElement()` |
| `mvt-refresh.js` | Принудительное обновление векторных тайлов | `refreshMVTTiles()` |
| `debug-grid.js` | Отладочная сетка границ тайлов | `DebugGrid` |
| `data-ws-client.js` | WebSocket для уведомлений Data Processor | `connectDataProcessorWS()` |

## Инициализация карты

Процесс инициализации выполняется в `map-main.js` и включает:
1. Загрузку конфигурации из Python через QWebChannel.
2. Создание экземпляра MapLibre с динамически сгенерированным стилем.
3. Инициализацию менеджеров (Points, Agent).
4. Экспонирование API в `window.app`.

```{.javascript caption="assets/js/map-main.js: Инициализация"}
export async function initializeMap() {
  if (mapInitialized) return;
  mapInitialized = true;

  // Load config from YAML first
  await loadMapConfig();
  const MAP_CONFIG = getMapConfig();

  const tileUrl = window.TILE_URL || MAP_CONFIG.tiles.defaultUrl;

  // Create map with both raster and vector tiles
  map = new maplibregl.Map({
    container: 'map',
    style: createMapStyle(tileUrl),
    center: MAP_CONFIG.initial.center,
    zoom: MAP_CONFIG.initial.zoom,
    hash: false,
    attributionControl: true,
    antialias: true,
    showTileBoundaries: true,  // DEBUG: Show tile boundaries
  });

  // Initialize managers
  pointsManager = new PointsManager(map);
  agentAnimator = new AgentAnimator(map);
  mapAPI = new MapAPI(map, pointsManager, agentAnimator);

  // Expose globally
  window.map = map;
  window.app = mapAPI;

  mapLoaded = true;
  pointsManager.setMapLoaded(true);
}
```

## Динамическая генерация стилей

MapLibre использует спецификацию стилей (Style Spec) — JSON-документ, описывающий источники данных (sources) и слои (layers). Стиль генерируется динамически на основе конфигурации YAML.

### Структура стиля

```{.mermaid}
graph TB
    subgraph "MapLibre Style"
        Sources[Sources<br/>Источники данных]
        Layers[Layers<br/>Слои рендеринга]
    end
    
    subgraph "Sources"
        OSM[osm<br/>Raster Tiles]
        GraphVector[graph-vector<br/>MVT Tiles]
        Routes[routes<br/>GeoJSON]
        KRoutes[k-routes<br/>GeoJSON]
    end
    
    subgraph "Layers"
        BG[background<br/>Фон]
        OSMLayer[osm<br/>Растровая подложка]
        LOD[LOD Layers<br/>4-уровневая система]
        RoutesLayer[routes<br/>Выбранный маршрут]
        KRoutesLayers[k-routes-*<br/>Альтернативы]
    end
    
    Sources --> Layers
    OSM --> OSMLayer
    GraphVector --> LOD
    Routes --> RoutesLayer
    KRoutes --> KRoutesLayers
    
    style Sources fill:#3b82f6,color:#fff
    style Layers fill:#22c55e,color:#fff
```

### Генерация LOD-слоёв

LOD (Level of Detail) — система прогрессивной детализации, где на разных уровнях зума отображаются разные типы дорог. Конфигурация задаётся в YAML:

```{.yaml caption="configs/client/map.lod.yaml (пример)"}
layers:
  - name: highways
    minzoom: 0
    maxzoom: 10
    highways: [motorway, trunk, primary]
    base_width: 2.0
    show_names: false
    
  - name: major
    minzoom: 10
    maxzoom: 13
    highways: [motorway, trunk, primary, secondary]
    base_width: 1.5
    show_names: true
```

Генератор преобразует конфигурацию в MapLibre layers:

```{.javascript caption="assets/js/map-style.js: Генерация LOD"}
function generateLodLayers(lodConfig, colors, widths) {
  const layers = [];
  for (const lod of lodConfig.layers) {
    const { name, minzoom, maxzoom, highways, show_names } = lod;

    // Build filter from highways list
    const filter = (highways && highways.length > 0) 
      ? ['in', 'highway', ...highways] 
      : null;

    // Build color expression
    const colorPairs = [];
    for (const hw of highways) {
      if (colors[hw]) {
        colorPairs.push(hw, colors[hw]);
      }
    }
    const colorExpression = ['match', ['get', 'highway'], ...colorPairs, '#353535ff'];

    // Build line-width based on highway type
    const baseWidth = lod.base_width || 1.0;
    const highwayWidthMatch = ['match', ['get', 'highway']];
    for (const hw of highways) {
      highwayWidthMatch.push(hw, widths[hw] || widths.default || 1.0);
    }
    highwayWidthMatch.push(1.0); // Default multiplier

    const layerDef = {
      id: `graph-${name}`,
      type: 'line',
      source: 'graph-vector',
      'source-layer': 'ways',
      minzoom,
      ...(maxzoom !== undefined && maxzoom !== null ? { maxzoom } : {}),
      ...(filter !== null ? { filter } : {}),
      layout: {
        'line-join': 'round',
        'line-cap': 'round'
      },
      paint: {
        'line-color': colorExpression,
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          minzoom, baseWidth,
          18, ['*', highwayWidthMatch, 1.5]
        ]
      }
    };

    layers.push(layerDef);

    // Add labels if enabled
    if (show_names) {
      layers.push({
        id: `graph-${name}-labels`,
        type: 'symbol',
        source: 'graph-vector',
        'source-layer': 'ways',
        minzoom: Math.max(minzoom, 12),
        filter: ['has', 'name'],
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': 12,
          'symbol-placement': 'line'
        },
        paint: {
          'text-color': '#000000',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2
        }
      });
    }
  }
  return layers;
}
```

### Векторные тайлы (MVT)

Источник `graph-vector` запрашивает тайлы у Data Processor через Gateway:

```{.javascript caption="assets/js/map-style.js: MVT Source"}
'graph-vector': {
  type: 'vector',
  tiles: [`${cfg.apiBaseUrl}/tiles/{z}/{x}/{y}.mvt?v=${Date.now()}`],
  minzoom: 0,
  maxzoom: 18
}
```

**Примечание:** Параметр `v=${Date.now()}` добавлен для обхода кеширования браузера при обновлении тайлов.

## Управление точками маршрута

`PointsManager` отвечает за визуализацию и управление точками маршрута (From, Via, To). Поддерживает:
- Установку начальной/конечной точки.
- Добавление промежуточных точек (Via).
- Автоматическое определение типа маркера по позиции в массиве.
- Отложенную инициализацию (pending operations) до загрузки карты.

### Типы маркеров

**Таблица: Типы маркеров**

| Тип | Позиция | Цвет | Размер |
|-----|---------|------|--------|
| `start` | Первая точка | Синий (#2563eb) | 16px |
| `end` | Последняя точка | Красный (#dc2626) | 16px |
| `via` | Промежуточные | Фиолетовый (#8b5cf6) | 10px |
| `agent` | Текущая позиция агента | Зелёный (#22c55e) | 16px |

### Отложенная инициализация

Проблема: QWebChannel и MapLibre инициализируются асинхронно. Если Python вызывает `setStart()` до готовности карты, маркер не отобразится.

Решение: Очередь отложенных операций (`pendingOperations`):

```{.javascript caption="assets/js/points-manager.js: Pending Operations"}
setStart(lngLat) {
  if (!this.mapLoaded) {
    this.pendingOperations.push({ type: 'setStart', lngLat });
    console.log('Map not loaded, queued setStart');
    return;
  }

  const lon = lngLat.lng !== undefined ? lngLat.lng : lngLat.lon;
  const point = {
    lon: lon,
    lat: lngLat.lat,
    color: lngLat.color || '#8b5cf6',
  };

  if (this.allPoints.length === 0) {
    this.allPoints.push(point);
  } else {
    this.allPoints[0] = point;
  }

  this._redrawAllMarkers();
}

setMapLoaded(loaded) {
  this.mapLoaded = loaded;
  if (loaded) {
    this._processPendingOperations();
  }
}
```

## Анимация агентов

`AgentAnimator` обеспечивает плавное движение маркера агента с интерполяцией позиции (linear interpolation, LERP). Это предотвращает "телепортацию" при обновлении координат.

### Алгоритм сглаживания

```{.javascript caption="assets/js/agent-animator.js: LERP Animation"}
animate(timestamp) {
  if (!this.agentCur || !this.agentTarget || !this.map) {
    return;
  }

  const dt = Math.min(
    (timestamp - this.lastFrame) / 1000,
    this.MAP_CONFIG.animation.maxFrameDelta
  );
  this.lastFrame = timestamp;

  const alpha = this.MAP_CONFIG.animation.agentSmoothing;  // 0.25
  const next = [
    this._lerp(this.agentCur[0], this.agentTarget[0], alpha),
    this._lerp(this.agentCur[1], this.agentTarget[1], alpha),
  ];

  this.agentCur = next;
  this.agentMarker.setLngLat(next);

  if (!this.agentMarker._map) {
    this.agentMarker.addTo(this.map);
  }
}

_lerp(a, b, t) {
  return a + (b - a) * t;
}
```

**Параметры:**
- `agentSmoothing = 0.25` — коэффициент сглаживания (чем меньше, тем плавнее, но с задержкой).
- `maxFrameDelta = 0.05` — максимальный шаг времени (50 мс) для предотвращения скачков при зависаниях.

### Поворот маркера

Маркер поворачивается в направлении движения (bearing):

```{.javascript caption="assets/js/agent-animator.js: Rotation"}
_rotateMarker(bearingDegrees) {
  if (!this.agentMarker) return;
  
  const el = this.agentMarker.getElement();
  if (!el) return;
  
  // Rotate marker to face direction of movement
  el.style.transform = `rotate(${bearingDegrees}deg)`;
}
```

## Реактивное обновление векторных тайлов

При изменении данных в Data Processor (загрузка нового тайла) клиент получает уведомление через WebSocket и принудительно обновляет затронутые тайлы.

### Схема обновления

```{.mermaid}
sequenceDiagram
    participant DataProc as Data Processor
    participant Gateway as Gateway
    participant WSClient as DataSocketClient (JS)
    participant MapAPI as MapAPI
    participant MapLibre as MapLibre GL JS
    
    Note over DataProc: Tile downloaded<br/>(z=12, x=2479, y=1279)
    DataProc->>Gateway: WS: {type: "tile_downloaded", z, x, y}
    Gateway->>WSClient: WS: {type: "tile_downloaded", z, x, y}
    WSClient->>MapAPI: window.app.refreshMVTTiles()
    MapAPI->>MapLibre: map.getSource('graph-vector').setTiles([...])
    Note over MapLibre: Force reload tiles<br/>with cache-busting
```

### Реализация

```{.javascript caption="assets/js/mvt-refresh.js"}
export function refreshMVTTiles(map, apiBaseUrl) {
  const source = map.getSource('graph-vector');
  if (!source) {
    console.warn('[MVT] graph-vector source not found');
    return;
  }

  const newTileUrl = `${apiBaseUrl}/tiles/{z}/{x}/{y}.mvt?v=${Date.now()}`;
  
  // Force reload by updating tiles URL with new timestamp
  source.setTiles([newTileUrl]);
  
  console.log('[MVT] Tiles refreshed:', newTileUrl);
}
```

**Примечание:** Параметр `v=${Date.now()}` обходит кеш браузера, заставляя MapLibre запросить тайлы заново.

## Отладочные инструменты

### Debug Grid

Визуализация границ тайлов для отладки LOD и кеширования:

```{.javascript caption="assets/js/debug-grid.js (фрагмент)"}
class DebugGrid {
  constructor(map) {
    this.map = map;
    this.enabled = false;
    this.overlay = null;
  }

  toggle() {
    this.enabled = !this.enabled;
    if (this.enabled) {
      this._createOverlay();
      this._updateGrid();
      this.map.on('moveend', this._updateGrid.bind(this));
    } else {
      this._removeOverlay();
      this.map.off('moveend', this._updateGrid);
    }
  }

  _updateGrid() {
    const bounds = this.map.getBounds();
    const zoom = Math.floor(this.map.getZoom());
    
    // Calculate tile coordinates
    const tiles = this._getTilesInBounds(bounds, zoom);
    
    // Draw grid
    this._drawTiles(tiles, zoom);
  }
}
```

Включение: `window.app.toggleDebugGrid()`.

## Публичный API (MapAPI)

`MapAPI` — фасад для взаимодействия Python с картой. Все методы доступны через `window.app`.

**Таблица: Методы MapAPI**

| Метод | Назначение | Параметры |
|-------|-----------|-----------|
| `setZoom(level)` | Установить зум | `level: number` |
| `getZoom()` | Получить текущий зум | — |
| `getBounds()` | Получить границы видимой области | — |
| `getCursorPosition()` | Получить координаты курсора | — |
| `setStart(lngLat)` | Установить начальную точку | `{lat, lon}` |
| `setEnd(lngLat)` | Установить конечную точку | `{lat, lon}` |
| `addViaPoint(lngLat)` | Добавить промежуточную точку | `{lat, lon}` |
| `clearPoints()` | Очистить все точки | — |
| `displayRoutes(routes)` | Отобразить маршруты | `routes: Array` |
| `highlightRoute(routeId)` | Выделить маршрут | `routeId: number` |
| `updateAgent(pos)` | Обновить позицию агента | `{lat, lon, bearing}` |
| `refreshMVTTiles()` | Обновить векторные тайлы | — |

### Пример вызова из Python

```{.python caption="ui/main_window_handlers.py: Вызов JS из Python"}
def _set_map_zoom_from_slider(self, position: int):
    """Set map zoom from slider (instant, no animation)."""
    self._skip_next_zoom_update = True
    
    js_code = f"window.app.setZoom({position});"
    self.web_view.page().runJavaScript(js_code)
```

## Выводы

Картографический движок на базе MapLibre GL JS обеспечил:
- **Производительность:** GPU-рендеринг позволяет отображать 200+ тыс. рёбер графа без деградации.
- **Гибкость:** Динамическая стилизация через конфигурацию YAML без изменения кода.
- **Модульность:** ES6-модули упрощают поддержку и тестирование.
- **Реактивность:** WebSocket-интеграция для обновления тайлов в реальном времени.

**Компромиссы:**
- **Сложность отладки:** Ошибки в JavaScript требуют инспектирования через Chrome DevTools.
- **Зависимость от браузера:** Производительность зависит от версии Chromium в QtWebEngine.
- **Накладные расходы:** Мост QWebChannel добавляет латентность при частых вызовах.

**Метрики:**
- Время инициализации карты: ~500 мс (включая загрузку конфигурации).
- Частота обновления анимации агента: 60 FPS (при `agentSmoothing = 0.25`).
- Размер JavaScript-кода: ~40 КБ (несжатый).

---

## Приложение: Конфигурация карты

```{.yaml caption="configs/client/map.yaml (фрагмент)"}
initial:
  center: [37.6173, 55.7558]  # Moscow center [lon, lat]
  zoom: 12
  minZoom: 0
  maxZoom: 19

animation:
  agentSmoothing: 0.25  # Lerp alpha for agent movement
  maxFrameDelta: 0.05   # Max seconds per animation frame
  zoomDuration: 200     # Milliseconds
  fitBoundsPadding: 40  # Pixels

tiles:
  tileSize: 256
  defaultUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
```
