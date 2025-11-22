/**
 * Main map initialization and setup.
 */

import { MAP_CONFIG } from './map-config.js';
import { createMapStyle } from './map-style.js';
import { PointsManager } from './points-manager.js';
import { AgentAnimator } from './agent-animator.js';
import { MapAPI } from './map-api.js';
import { startMVTRefresh } from './mvt-refresh.js';

let mapInitialized = false;
let map = null;
let mapAPI = null;
let pointsManager = null;
let agentAnimator = null;
let mapLoaded = false;

// Track last mouse position for Ctrl shortcuts
let lastMousePosition = null;
let lastContextMenuPos = null;

// Helper function to log to Python via QWebChannel
function logToPython(message) {
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    // Fallback to console if bridge not ready
    console.log(message);
  }
}

export function initializeMap() {
  if (mapInitialized) return;
  mapInitialized = true;

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
  });

  // Initialize managers
  pointsManager = new PointsManager(map);
  agentAnimator = new AgentAnimator(map);
  mapAPI = new MapAPI(map, pointsManager, agentAnimator);

  // Expose globally
  window.map = map;
  window.app = mapAPI;

  // Mark as loaded immediately
  mapLoaded = true;
  pointsManager.setMapLoaded(true);
  console.log('Map initialized, marking as loaded');
  
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

  // Map load event for additional initialization
  map.on('load', () => {
    logToPython('[MAP] Tiles loaded successfully');
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
      console.log('[MapLibre error]', msg);
    } catch (err) {
      // ignore
    }
  });

  // Initialize QWebChannel ONCE for all bridges (zoom, points, etc)
  // Store globally so other scripts can reuse it
  window.globalChannel = null;
  
  if (window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, async function(channel) {
      window.globalChannel = channel;
      console.log('[map-main.js] QWebChannel initialized globally');
      
      // Setup zoom bridge
      if (channel.objects.zoom_bridge) {
        console.log('[map-main.js] Zoom bridge registered');
      }
      
      // Initialize debug overlay if enabled in config
      if (channel.objects.config_bridge && typeof window.initDebugOverlay === 'function') {
        // QWebChannel methods return Promises even with result= annotation
        const enabled = await channel.objects.config_bridge.isDebugEnabled();
        console.log(`[map-main.js] Debug mode: ${enabled}`);
        await window.initDebugOverlay(enabled);
      }
    });
  }

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
    console.log('Right-click at:', lastContextMenuPos);
    
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

// Auto-initialize when TILE_URL is available
if (window.TILE_URL) {
  initializeMap();
} else {
  setTimeout(() => {
    if (window.TILE_URL) {
      initializeMap();
    } else {
      console.error('TILE_URL NOT SET! Using OSM fallback.');
      window.TILE_URL = MAP_CONFIG.tiles.defaultUrl;
      initializeMap();
    }
  }, 500);
}
