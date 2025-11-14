/**
 * Main map initialization and setup.
 */

import { MAP_CONFIG } from './map-config.js';
import { createMapStyle } from './map-style.js';
import { PointsManager } from './points-manager.js';
import { AgentAnimator } from './agent-animator.js';
import { MapAPI } from './map-api.js';

let mapInitialized = false;
let map = null;
let mapAPI = null;
let pointsManager = null;
let agentAnimator = null;
let mapLoaded = false;

// Track last mouse position for Ctrl shortcuts
let lastMousePosition = null;
let lastContextMenuPos = null;

export function initializeMap() {
  if (mapInitialized) return;
  mapInitialized = true;

  const tileUrl = window.TILE_URL || MAP_CONFIG.tiles.defaultUrl;
  console.log('Initializing map with tile URL:', tileUrl);

  // Create map
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

  // Setup event listeners
  setupEventListeners();

  // Start animation loop
  function animate(ts) {
    requestAnimationFrame(animate);
    agentAnimator.animate(ts);
  }
  requestAnimationFrame(animate);

  // Optional: setup map load callback for tile loading
  map.on('load', () => {
    console.log('Map tiles loaded successfully');
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

  // Zoom tracking via QWebChannel (initialized once)
  let zoomBridgeChannel = null;
  if (window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, function(channel) {
      zoomBridgeChannel = channel;
    });
  }

  map.on('zoom', () => {
    const zoom = Math.floor(map.getZoom());
    const fromUI = !mapAPI.shouldSkipZoomUpdate();

    if (fromUI && zoomBridgeChannel && zoomBridgeChannel.objects.zoom_bridge) {
      zoomBridgeChannel.objects.zoom_bridge.notify_zoom(zoom);
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
    if (window.onMapContextMenu) {
      window.onMapContextMenu(lastContextMenuPos);
    }
  });
}

// Auto-initialize when TILE_URL is available
console.log('Script started, checking for TILE_URL...');
if (window.TILE_URL) {
  console.log('TILE_URL found immediately:', window.TILE_URL);
  initializeMap();
} else {
  console.log('TILE_URL not found, waiting 100ms...');
  setTimeout(() => {
    if (window.TILE_URL) {
      console.log('TILE_URL found after delay:', window.TILE_URL);
      initializeMap();
    } else {
      console.error('TILE_URL NOT SET! Using OSM fallback.');
      window.TILE_URL = MAP_CONFIG.tiles.defaultUrl;
      initializeMap();
    }
  }, 100);
}
