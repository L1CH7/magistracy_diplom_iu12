/**
 * Debug Grid Overlay for Map
 * 
 * Visualizes:
 * - default_bbox (cyan dashed border)
 * - OSM tile grid (black thin lines aligned to tile coordinates)
 * - Loaded tiles (green fill with opacity)
 * 
 * Controlled by configs/client/gui.yaml (debug.enabled)
 * Styles from configs/client/debug.yaml
 */

// Helper to log to Python via QWebChannel
function logToPython(message) {
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    console.log(message); // Fallback
  }
}

logToPython('[debug-grid.js] Script loaded');

let debugConfig = null;
let debugStyles = null;
let debugLayersAdded = false;
let debugEnabled = false; // Set from GUI config

/**
 * Fetch debug configuration from Data Processor.
 */
async function fetchDebugConfig() {
  try {
    const baseUrl = (window.MAP_CONFIG && window.MAP_CONFIG.apiBaseUrl) || 'http://localhost:8000';
    logToPython(`[Debug] Fetching config from ${baseUrl}/debug/config`);
    const response = await fetch(`${baseUrl}/debug/config`);
    if (!response.ok) {
      logToPython(`[Debug] ERROR: Failed to fetch config: ${response.status}`);
      return null;
    }
    const config = await response.json();
    logToPython(`[Debug] Config loaded: tile_size=${config.tile_size_degrees}°`);

    // Экспортируем в window для доступа из map-main.js
    window.debugConfig = config;

    return config;
  } catch (error) {
    logToPython(`[Debug] ERROR: Error fetching config: ${error}`);
    return null;
  }
}

/**
 * Fetch list of loaded tiles from Data Processor.
 */
async function fetchLoadedTiles() {
  try {
    logToPython('[Debug] Fetching loaded tiles from /debug/loaded-tiles');
    const baseUrl = (window.MAP_CONFIG && window.MAP_CONFIG.apiBaseUrl) || 'http://localhost:8000';
    const response = await fetch(`${baseUrl}/debug/loaded-tiles`);
    if (!response.ok) {
      logToPython(`[Debug] ERROR: Failed to fetch loaded tiles: ${response.status}`);
      return [];
    }
    const tileKeys = await response.json();
    logToPython(`[Debug] Loaded tiles count: ${tileKeys.length}`);

    // Convert tile keys ['37.30_55.45', ...] to [lon, lat] pairs
    const tiles = tileKeys.map(key => {
      const [lon, lat] = key.split('_').map(parseFloat);
      return [lon, lat];
    });

    return tiles;
  } catch (error) {
    logToPython(`[Debug] ERROR: Error fetching loaded tiles: ${error}`);
    return [];
  }
}

/**
 * Load debug styles from config.
 */
function getDebugStyles() {
  if (!debugConfig) {
    // Fallback если конфиг не загружен
    logToPython('[Debug] WARNING: getDebugStyles called without config, using fallback');
    return {
      bbox_border: {
        color: '#00ffff',
        width: 3,
        dasharray: [4, 4],
        opacity: 0.9
      },
      tile_grid: {
        color: '#000000',
        width: 0.5,
        opacity: 0.4
      },
      loaded_tiles: {
        fill_color: '#00ff00',
        fill_opacity: 0.15,
        border_color: '#00aa00',
        border_width: 1,
        border_opacity: 0.3
      }
    };
  }

  // Используем стили из конфига
  return {
    bbox_border: {
      color: debugConfig.bbox_border?.color || '#00ffff',
      width: debugConfig.bbox_border?.width || 3,
      dasharray: debugConfig.bbox_border?.dasharray || [4, 4],
      opacity: debugConfig.bbox_border?.opacity || 0.9
    },
    tile_grid: {
      color: debugConfig.grid.color,
      width: debugConfig.grid.width,
      opacity: debugConfig.grid.opacity
    },
    loaded_tiles: {
      fill_color: debugConfig.loaded_tiles.fill_color,
      fill_opacity: debugConfig.loaded_tiles.fill_opacity,
      border_color: debugConfig.loaded_tiles.border_color,
      border_width: debugConfig.loaded_tiles.border_width,
      border_opacity: debugConfig.loaded_tiles.border_opacity
    }
  };
}

/**
 * Generate GeoJSON for default bbox border.
 */
function generateBboxBorder(bbox) {
  const { west, south, east, north } = bbox;
  return {
    type: 'Feature',
    properties: { type: 'default_bbox' },
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south]
      ]]
    }
  };
}

/**
 * Generate GeoJSON for OSM tile grid.
 * Creates vertical and horizontal lines aligned to tile_size grid.
 */
function generateTileGrid(bbox, tileSize, mapBounds) {
  const features = [];
  const { west, south, east, north } = bbox;

  // Extend grid to map viewport to see tiles outside bbox
  const viewWest = Math.min(west, mapBounds.getWest());
  const viewEast = Math.max(east, mapBounds.getEast());
  const viewSouth = Math.min(south, mapBounds.getSouth());
  const viewNorth = Math.max(north, mapBounds.getNorth());

  // Calculate grid starting points (aligned to tile_size)
  const startLon = Math.floor(viewWest / tileSize) * tileSize;
  const startLat = Math.floor(viewSouth / tileSize) * tileSize;

  // Vertical lines (longitude)
  for (let lon = startLon; lon <= viewEast; lon += tileSize) {
    features.push({
      type: 'Feature',
      properties: { type: 'grid_line', coord: lon.toFixed(2) },
      geometry: {
        type: 'LineString',
        coordinates: [
          [lon, viewSouth],
          [lon, viewNorth]
        ]
      }
    });
  }

  // Horizontal lines (latitude)
  for (let lat = startLat; lat <= viewNorth; lat += tileSize) {
    features.push({
      type: 'Feature',
      properties: { type: 'grid_line', coord: lat.toFixed(2) },
      geometry: {
        type: 'LineString',
        coordinates: [
          [viewWest, lat],
          [viewEast, lat]
        ]
      }
    });
  }

  return features;
}

/**
 * Generate GeoJSON for loaded tiles (green rectangles).
 */
function generateLoadedTiles(tiles, tileSize) {
  return tiles.map(([lon, lat]) => ({
    type: 'Feature',
    properties: { type: 'loaded_tile', lon, lat },
    geometry: {
      type: 'Polygon',
      coordinates: [[
        [lon, lat],
        [lon + tileSize, lat],
        [lon + tileSize, lat + tileSize],
        [lon, lat + tileSize],
        [lon, lat]
      ]]
    }
  }));
}

/**
 * Add debug layers to map.
 */
async function addDebugLayers() {
  logToPython('[Debug] addDebugLayers called');

  if (!window.map || !debugConfig) {
    logToPython('[Debug] ERROR: Map or config not available');
    return;
  }

  if (debugLayersAdded) {
    logToPython('[Debug] Layers already added, refreshing data');
    refreshDebugLayers();
    return;
  }

  const map = window.map;
  logToPython('[Debug] Adding debug sources and layers...');

  try {

    // Add sources (check if not exists first)
    if (!map.getSource('debug-bbox')) {
      map.addSource('debug-bbox', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [generateBboxBorder(debugConfig.default_bbox)]
        }
      });
    }

    if (!map.getSource('debug-grid')) {
      map.addSource('debug-grid', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: generateTileGrid(
            debugConfig.default_bbox,
            debugConfig.tile_size_degrees,
            map.getBounds()
          )
        }
      });
    }

    if (!map.getSource('debug-tiles')) {
      // Загружаем loaded tiles асинхронно
      const loadedTiles = await fetchLoadedTiles();
      const tileFeatures = generateLoadedTiles(
        loadedTiles,
        debugConfig.tile_size_degrees
      );

      map.addSource('debug-tiles', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: tileFeatures
        }
      });

      logToPython(`[Debug] Added ${tileFeatures.length} loaded tile features`);
    }

    // Load styles
    const styles = getDebugStyles();

    // Add layers (check if not exists first)
    // 1. Loaded tiles (green fill, lowest z-order)
    if (!map.getLayer('debug-tiles-fill')) {
      map.addLayer({
        id: 'debug-tiles-fill',
        type: 'fill',
        source: 'debug-tiles',
        paint: {
          'fill-color': styles.loaded_tiles.fill_color,
          'fill-opacity': styles.loaded_tiles.fill_opacity
        }
      });
    }

    // 2. Grid lines (black thin)
    if (!map.getLayer('debug-grid-lines')) {
      map.addLayer({
        id: 'debug-grid-lines',
        type: 'line',
        source: 'debug-grid',
        paint: {
          'line-color': styles.tile_grid.color,
          'line-width': styles.tile_grid.width,
          'line-opacity': styles.tile_grid.opacity
        }
      });
    }

    // 3. Default bbox border (cyan dashed, highest z-order)
    if (!map.getLayer('debug-bbox-border')) {
      map.addLayer({
        id: 'debug-bbox-border',
        type: 'line',
        source: 'debug-bbox',
        paint: {
          'line-color': styles.bbox_border.color,
          'line-width': styles.bbox_border.width,
          'line-dasharray': styles.bbox_border.dasharray,
          'line-opacity': styles.bbox_border.opacity
        }
      });
    }

    debugLayersAdded = true;
    window.debugLayersVisible = true;
    logToPython('[Debug] Layers added successfully');

    // Update grid on map move
    map.on('moveend', refreshDebugLayers);

  } catch (error) {
    logToPython(`[Debug] ERROR adding layers: ${error.message}`);
    console.error('[Debug] Layer add failed:', error);
  }
}

/**
 * Refresh debug layers (update grid for current viewport).
 */
function refreshDebugLayers() {
  if (!window.map || !debugConfig || !debugLayersAdded) {
    return;
  }

  const map = window.map;

  // Update grid
  const gridSource = map.getSource('debug-grid');
  if (gridSource) {
    gridSource.setData({
      type: 'FeatureCollection',
      features: generateTileGrid(
        debugConfig.default_bbox,
        debugConfig.tile_size_degrees,
        map.getBounds()
      )
    });
  }
}

/**
 * Remove debug layers from map.
 */
function removeDebugLayers() {
  if (!window.map || !debugLayersAdded) {
    return;
  }

  const map = window.map;

  if (map.getLayer('debug-bbox-border')) map.removeLayer('debug-bbox-border');
  if (map.getLayer('debug-grid-lines')) map.removeLayer('debug-grid-lines');
  if (map.getLayer('debug-tiles-fill')) map.removeLayer('debug-tiles-fill');

  if (map.getSource('debug-bbox')) map.removeSource('debug-bbox');
  if (map.getSource('debug-grid')) map.removeSource('debug-grid');
  if (map.getSource('debug-tiles')) map.removeSource('debug-tiles');

  debugLayersAdded = false;
  window.debugLayersVisible = false;
  console.log('[Debug] Layers removed');
}

/**
 * Toggle debug overlay.
 */
async function toggleDebugOverlay() {
  if (!debugEnabled) {
    logToPython('[Debug] Debug mode disabled in config (gui.yaml)');
    return;
  }

  // Check if map is ready
  if (!window.map) {
    logToPython('[Debug] ERROR: Map not initialized yet');
    return;
  }

  // Wait for style.load if not loaded yet (async)
  if (!window.map.isStyleLoaded()) {
    logToPython('[Debug] Map style not loaded yet, waiting for style.load event...');
    window.map.once('style.load', async () => {
      logToPython('[Debug] Style loaded, adding debug layers now');
      await toggleDebugOverlay(); // Retry after style loads
    });
    return;
  }

  if (!debugLayersAdded) {
    // Enable debug mode
    if (!debugConfig) {
      debugConfig = await fetchDebugConfig();
      if (!debugConfig) {
        logToPython('[Debug] ERROR: Failed to load config');
        return;
      }
    }
    await addDebugLayers();
    logToPython('[Debug] Debug overlay ENABLED');
  } else {
    // Disable debug mode
    removeDebugLayers();
    logToPython('[Debug] Debug overlay DISABLED');
  }
}

/**
 * Initialize debug overlay based on GUI config.
 * Called from map-main.js after QWebChannel is ready.
 * If enabled=true, automatically shows overlay after map loads.
 */
async function initDebugOverlay(enabled) {
  logToPython(`[debug-grid.js] initDebugOverlay called with enabled = ${enabled}`);
  debugEnabled = enabled;
  if (enabled) {
    // Загружаем конфиг заранее для доступа из map-main.js (ПКМ)
    if (!debugConfig) {
      debugConfig = await fetchDebugConfig();
      if (!debugConfig) {
        logToPython('[debug-grid.js] ERROR: Failed to load debug config');
      }
    }

    logToPython('[debug-grid.js] Debug mode enabled (Ctrl+Shift+D to toggle overlay)');
    // Do NOT auto-show overlay, only prepare for Ctrl+Shift+D toggle
    logToPython('[debug-grid.js] Debug overlay ready, press Ctrl+Shift+D to show');
  } else {
    logToPython('[debug-grid.js] Debug mode DISABLED in config (gui.yaml)');
    logToPython('[debug-grid.js] Set debug.enabled=true to enable debug overlay');
  }
}

// Export for global access
window.toggleDebugOverlay = toggleDebugOverlay;
window.initDebugOverlay = initDebugOverlay;

// Getter for debug enabled state
Object.defineProperty(window, 'debugEnabled', {
  get: function () { return debugEnabled; }
});

// Ctrl+Shift+D toggle (only works if debug enabled in config)
// Ctrl+Shift+V show viewport bbox
document.addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.shiftKey && e.key === 'D') {
    e.preventDefault();
    if (debugEnabled) {
      toggleDebugOverlay();
    } else {
      logToPython('[debug-grid.js] Ctrl+Shift+D pressed, but debug.enabled=false in config');
      logToPython('[debug-grid.js] Enable debug mode in configs/client/gui.yaml to use overlay');
    }
  }

  // Ctrl+Shift+V: Show current viewport bbox
  if (e.ctrlKey && e.shiftKey && e.key === 'V') {
    e.preventDefault();
    if (!window.map) {
      logToPython('[debug-grid.js] Map not initialized');
      return;
    }
    const bounds = window.map.getBounds();
    const bbox = {
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth()
    };
    const zoom = window.map.getZoom();
    const center = window.map.getCenter();

    logToPython(`[VIEWPORT] zoom=${zoom.toFixed(2)} center=[${center.lng.toFixed(4)}, ${center.lat.toFixed(4)}]`);
    logToPython(`[VIEWPORT] bbox=[${bbox.west.toFixed(4)}, ${bbox.south.toFixed(4)}, ${bbox.east.toFixed(4)}, ${bbox.north.toFixed(4)}]`);
    console.log('Viewport bbox:', bbox);
    console.log('Zoom:', zoom, 'Center:', center);
  }
});

/**
 * Redownload tile at specific coordinates.
 * Called from right-click context menu in debug mode.
 */
async function redownloadTileAt(lon, lat) {
  if (!debugEnabled) {
    logToPython('[Debug] Redownload only available in debug mode');
    return;
  }

  if (!debugConfig) {
    logToPython('[Debug] Config not loaded, fetching...');
    debugConfig = await fetchDebugConfig();
    if (!debugConfig) {
      alert('Failed to load debug config');
      return;
    }
  }

  const TILE_SIZE = debugConfig.tile_size_degrees;
  const tileX = Math.floor(lon / TILE_SIZE) * TILE_SIZE;
  const tileY = Math.floor(lat / TILE_SIZE) * TILE_SIZE;

  // Вычисляем количество знаков после запятой для tile_key
  const precision = Math.max(2, -Math.floor(Math.log10(TILE_SIZE)) + 1);
  const tileKey = `${tileX.toFixed(precision)}_${tileY.toFixed(precision)}`;

  // Вычисляем bbox тайла (4 координаты)
  const tileBbox = {
    west: tileX,
    south: tileY,
    east: tileX + TILE_SIZE,
    north: tileY + TILE_SIZE
  };

  logToPython(`[Debug] Redownload bbox: [${tileBbox.west.toFixed(precision)}, ${tileBbox.south.toFixed(precision)}, ${tileBbox.east.toFixed(precision)}, ${tileBbox.north.toFixed(precision)}]`);

  try {
    const baseUrl = (window.MAP_CONFIG && window.MAP_CONFIG.apiBaseUrl) || 'http://localhost:8000';
    const url = `${baseUrl}/tiles/redownload?west=${tileBbox.west}&south=${tileBbox.south}&east=${tileBbox.east}&north=${tileBbox.north}`;
    const response = await fetch(url, { method: 'POST' });

    if (!response.ok) {
      const error = await response.json();
      logToPython(`[Debug] Redownload failed: ${error.detail}`);
      alert(`Redownload failed: ${error.detail}`);
      return;
    }

    const result = await response.json();
    logToPython(`[Debug] Redownload started for bbox: ${JSON.stringify(result.bbox)}`);
    alert(`Redownload started for bbox.\nWait ~20s for completion.`);

    // Refresh overlay and MVT tiles after 20 seconds
    setTimeout(() => {
      if (debugLayersAdded && window.map) {
        logToPython('[Debug] Refreshing overlay after redownload');
        refreshDebugLayers();
      }
      // Force MVT tile refresh
      if (window.app && window.app.refreshMVTTiles) {
        window.app.refreshMVTTiles();
      }
    }, 20000);

  } catch (error) {
    logToPython(`[Debug] Redownload error: ${error}`);
    alert(`Error: ${error.message}`);
  }
}

// Export for map context menu
window.redownloadTileAt = redownloadTileAt;

console.log('[debug-grid.js] Debug grid module loaded');
