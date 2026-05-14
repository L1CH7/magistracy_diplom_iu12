/**
 * Main map initialization and setup.
 */

import { loadMapConfig, getMapConfig } from './map-config-loader.js';
import { getBaseStyle, addOsmRaster, addRoadLabels } from './map-style.js';  
import { PointsManager } from './points-manager.js';
import { AgentAnimator } from './agent-animator.js';
import { MapAPI } from './map-api.js';
import { connectDataProcessorWS } from './data-ws-client.js';
import { TrafficHeatmap } from './traffic-heatmap.js';

let mapInitialized = false;
let map = null;
let mapAPI = null;
let pointsManager = null;
let agentAnimator = null;
let mapLoaded = false;

// Track last mouse position for Ctrl shortcuts
let lastMousePosition = null;
let lastContextMenuPos = null;

// Helper function to check URL availability (e.g. OSM server)
async function checkUrlAvailability(url, timeout = 3000) {
  return new Promise((resolve) => {
    const img = new Image();
    const timer = setTimeout(() => {
      img.src = "";
      resolve(false);
    }, timeout);

    img.onload = () => {
      clearTimeout(timer);
      resolve(true);
    };

    img.onerror = () => {
      clearTimeout(timer);
      resolve(false);
    };

    // Use a small 1x1 transparent pixel or just the URL if it's an image service
    // For OSM tiles, we can try to load a sample tile or just the base URL
    const testUrl = url.replace('{z}', '0').replace('{x}', '0').replace('{y}', '0');
    img.src = testUrl;
  });
}

// Helper function to log to Python via QWebChannel
function logToPython(message) {
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    // Fallback to console if bridge not ready
    console.log(message);
  }
}

export async function initializeMap() {
  if (mapInitialized) return;
  mapInitialized = true;

  // Load config from YAML first
  await loadMapConfig();
  const MAP_CONFIG = getMapConfig();
  const tileUrl = window.TILE_URL || MAP_CONFIG.tiles.defaultUrl;

  map = new maplibregl.Map({
    container: 'map',
    style: getBaseStyle(),
    center: MAP_CONFIG.initial.center,
    zoom: MAP_CONFIG.initial.zoom,
    hash: false,
    attributionControl: true,
    antialias: true
  });

  // Initialize managers
  pointsManager = new PointsManager(map);
  agentAnimator = new AgentAnimator(map);
  const trafficHeatmap = new TrafficHeatmap(map);
  mapAPI = new MapAPI(map, pointsManager, agentAnimator);

  // Expose globally
  window.map = map;
  window.app = mapAPI;
  mapLoaded = true;
  pointsManager.setMapLoaded(true);
  logToPython('[MAP] Initialized, marking as loaded');
  
  // Log viewport changes (for debugging)
  map.on('moveend', () => {
    const bounds = map.getBounds();
    const center = map.getCenter();
    const zoom = map.getZoom();
    const message = (
      `[MAP] moveend | z:${zoom.toFixed(1)} | ` +
      `c:[${center.lng.toFixed(4)}, ${center.lat.toFixed(4)}] | ` +
      `bbox:[${bounds.getWest().toFixed(4)}, ${bounds.getSouth().toFixed(4)}, ` +
      `${bounds.getEast().toFixed(4)}, ${bounds.getNorth().toFixed(4)}]`
    );
    logToPython(message);
  });

  // Setup event listeners
  setupEventListeners();

  // Start animation loop
  function animate(ts) {
    requestAnimationFrame(animate);
    agentAnimator.animate(ts);
  }
  requestAnimationFrame(animate);

  // Map load event for final initialization
  map.on('load', async () => {
    logToPython('[MAP] Base vector layers loaded');
    
    // Check OSM availability and inject if available
    if (tileUrl) {
      const isAvailable = await checkUrlAvailability(tileUrl);
      if (isAvailable) {
        logToPython('[MAP] OSM server is up. Adding raster and labels...');
        addOsmRaster(map, tileUrl, MAP_CONFIG.tiles.tileSize);
        if (MAP_CONFIG.style && MAP_CONFIG.style.glyphs) {
          addRoadLabels(map, MAP_CONFIG.style.glyphs);
        }
      } else {
        logToPython('[MAP] OSM server unreachable. Proceeding in sterile mode.');
      }
    }

    // Connect to Data Processor WebSocket AFTER map is fully ready
    logToPython('[map-main.js] Connecting to Data Processor WebSocket...');
    connectDataProcessorWS();
  });
}

function setupEventListeners() {
  // Track mouse position
  map.on('mousemove', (e) => {
    lastMousePosition = { lon: e.lngLat.lng, lat: e.lngLat.lat };
    window.lastMousePosition = lastMousePosition;
  });

  // Error logging
  map.on('error', (e) => {
    try {
      const msg = e && e.error && e.error.message ? e.error.message : JSON.stringify(e);
      logToPython(`[MapLibre error] ${msg}`);
    } catch (err) {
      // ignore
    }
  });

  map.on('zoom', () => {
    const zoom = Math.floor(map.getZoom());
    const fromUI = !mapAPI.shouldSkipZoomUpdate();

    // Use global channel
    if (fromUI && window.globalChannel && 
        window.globalChannel.objects.zoom_bridge) {
      window.globalChannel.objects.zoom_bridge.notify_zoom(zoom);
    }

    if (window.onZoomChanged) {
      window.onZoomChanged(zoom, fromUI);
    }
  });

  // Right-click context menu
  map.getCanvas().addEventListener('contextmenu', (e) => {
    e.preventDefault();
    lastContextMenuPos = map.unproject([e.clientX, e.clientY]);
    window.lastContextMenuPos = lastContextMenuPos;
    logToPython(`[MAP] Right-click at: ${JSON.stringify(lastContextMenuPos)}`);
    
    // Debug mode: redownload tile on right-click
    if (window.redownloadTileAt && typeof window.redownloadTileAt === 'function') {
      // Check if debug overlay is VISIBLE (not just enabled in config)
      const debugActive = window.debugEnabled && window.debugLayersVisible;
      if (debugActive) {
        // Рассчитываем bbox тайла
        if (window.debugConfig) {
          const TILE_SIZE = window.debugConfig.tile_size_degrees;
          const lon = lastContextMenuPos.lng;
          const lat = lastContextMenuPos.lat;
          const tileX = Math.floor(lon / TILE_SIZE) * TILE_SIZE;
          const tileY = Math.floor(lat / TILE_SIZE) * TILE_SIZE;
          const tileBbox = {
            west: tileX,
            south: tileY,
            east: tileX + TILE_SIZE,
            north: tileY + TILE_SIZE
          };
          
          // Добавляем временную подсветку тайла
          if (!map.getSource('debug-highlight-tile')) {
            map.addSource('debug-highlight-tile', {
              type: 'geojson',
              data: {
                type: 'Feature',
                geometry: {
                  type: 'Polygon',
                  coordinates: [[
                    [tileBbox.west, tileBbox.south],
                    [tileBbox.east, tileBbox.south],
                    [tileBbox.east, tileBbox.north],
                    [tileBbox.west, tileBbox.north],
                    [tileBbox.west, tileBbox.south]
                  ]]
                }
              }
            });
            
            map.addLayer({
              id: 'debug-highlight-tile-fill',
              type: 'fill',
              source: 'debug-highlight-tile',
              paint: {
                'fill-color': '#ff0000',
                'fill-opacity': 0.3
              }
            });
            
            map.addLayer({
              id: 'debug-highlight-tile-border',
              type: 'line',
              source: 'debug-highlight-tile',
              paint: {
                'line-color': '#ff0000',
                'line-width': 2
              }
            });
          } else {
            // Обновляем существующую подсветку
            map.getSource('debug-highlight-tile').setData({
              type: 'Feature',
              geometry: {
                type: 'Polygon',
                coordinates: [[
                  [tileBbox.west, tileBbox.south],
                  [tileBbox.east, tileBbox.south],
                  [tileBbox.east, tileBbox.north],
                  [tileBbox.west, tileBbox.north],
                  [tileBbox.west, tileBbox.south]
                ]]
              }
            });
          }
          
          const confirmed = confirm(
            `Redownload tile bbox?\n\n` +
            `West: ${tileBbox.west.toFixed(4)}°\n` +
            `South: ${tileBbox.south.toFixed(4)}°\n` +
            `East: ${tileBbox.east.toFixed(4)}°\n` +
            `North: ${tileBbox.north.toFixed(4)}°\n\n` +
            'This will force re-fetch OSM data for this tile.'
          );
          
          // Убираем подсветку после confirm
          if (map.getLayer('debug-highlight-tile-fill')) {
            map.removeLayer('debug-highlight-tile-fill');
          }
          if (map.getLayer('debug-highlight-tile-border')) {
            map.removeLayer('debug-highlight-tile-border');
          }
          if (map.getSource('debug-highlight-tile')) {
            map.removeSource('debug-highlight-tile');
          }
          
          if (confirmed) {
            window.redownloadTileAt(lon, lat);
          }
        }
      }
    }
    
    // Call Python context menu handler if exists
    if (window.onMapContextMenu) {
      window.onMapContextMenu(lastContextMenuPos);
    }
  });
}

// Entry point: Initialize MapLibre when DOM is ready AND QWebChannel is established
document.addEventListener("DOMContentLoaded", () => {
    console.log("[map-main.js] DOM ready, connecting to QWebChannel...");
    
    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, async function (channel) {
            window.globalChannel = channel;
            
            // Bridge registration
            window.points_bridge = channel.objects.points_bridge;
            
            // Setup Points Callback (Architect's Requirement)
            window.pointsChangedCallback = function() {
                if (window.points_bridge) {
                    console.log("[JS] Notifying Python about point changes");
                    window.points_bridge.notify_points_changed();
                }
            };

            // Initialize debug overlay if bridge exists
            if (channel.objects.config_bridge && typeof window.initDebugOverlay === 'function') {
                const enabled = await channel.objects.config_bridge.isDebugEnabled();
                await window.initDebugOverlay(enabled);
            }
            
            // Start the main app logic ONLY after channel is ready
            if (!mapInitialized) {
                await initializeMap();
            }
        });
    } else {
        console.warn("[map-main.js] QWebChannel not found, fallback to standalone");
        if (!mapInitialized) {
            initializeMap();
        }
    }
});
