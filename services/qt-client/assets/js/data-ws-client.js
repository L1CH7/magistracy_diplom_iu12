/**
 * Data Processor WebSocket Client
 * 
 * Replaces periodic polling (/api/v1/status) with real-time WebSocket events.
 * Receives notifications when OSM data is saved → triggers MVT tile refresh.
 */

import { getMapConfig } from './map-config-loader.js';

let wsConnection = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_DELAY_MS = 3000;

/**
 * Connect to Data Processor WebSocket.
 */
export function connectDataProcessorWS() {
  if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
    console.log('[DataWS] Already connected');
    return;
  }

  const config = getMapConfig();
  const baseUrl = (config && config.apiBaseUrl) || 'http://localhost:8000';
  const wsBase = baseUrl.replace(/^http/, 'ws');
  const wsUrl = `${wsBase}/ws/data_updates`;
  console.log(`[DataWS] Connecting to ${wsUrl}...`);

  try {
    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
      console.log('[DataWS] Connected successfully');
      reconnectAttempts = 0;

      // Send initial ping
      wsConnection.send(JSON.stringify({ type: 'ping' }));

      // Send current LOD config to sync with server
      const lodConfig = config.lod;
      if (lodConfig) {
        console.log('[DataWS] Sending LOD config...');
        wsConnection.send(JSON.stringify({
          type: 'config',
          lod: lodConfig
        }));
      }

      // Heartbeat: send ping every 20 seconds
      setInterval(() => {
        if (wsConnection.readyState === WebSocket.OPEN) {
          wsConnection.send(JSON.stringify({ type: 'ping' }));
        }
      }, 20000);
    };

    wsConnection.onmessage = (event) => {
      // Handle pong response (plain text)
      if (event.data === 'pong') {
        return;
      }

      // Handle JSON messages
      try {
        const message = JSON.parse(event.data);
        handleMessage(message);
      } catch (error) {
        console.error('[DataWS] Failed to parse message:', error, event.data);
      }
    };

    wsConnection.onerror = (error) => {
      console.error('[DataWS] Connection error:', error);
    };

    wsConnection.onclose = () => {
      console.log('[DataWS] Connection closed');
      wsConnection = null;

      // Attempt reconnection
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        console.log(
          `[DataWS] Reconnecting in ${RECONNECT_DELAY_MS}ms ` +
          `(attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`
        );
        setTimeout(connectDataProcessorWS, RECONNECT_DELAY_MS);
      } else {
        console.error('[DataWS] Max reconnection attempts reached');
      }
    };
  } catch (error) {
    console.error('[DataWS] Failed to create WebSocket:', error);
  }
}

/**
 * Handle incoming WebSocket messages.
 */
function handleMessage(message) {
  const { type, count } = message;

  switch (type) {
    case 'ways_updated':
      console.log(`[DataWS] Ways updated: ${count} total ways`);
      handleWaysUpdated(count);
      break;

    case 'tiles_invalidated':
      console.log('[DataWS] Tiles invalidated, refreshing...');
      handleTilesInvalidated();
      break;

    case 'ping':
      // Server keepalive ping
      break;

    case 'pong':
      // Server response to our ping
      break;

    default:
      console.warn(`[DataWS] Unknown message type: ${type}`);
  }
}

/**
 * Handle ways_updated event: refresh MVT tiles.
 */
function handleWaysUpdated(count) {
  if (!window.app) {
    console.warn('[DataWS] Map not initialized, skipping refresh');
    return;
  }

  // Refresh MVT tiles (new data available)
  window.app.refreshMVTTiles();

  // Log to Python if bridge available
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(
      `[DataWS] Refreshed tiles (${count} ways)`
    );
  }
}

/**
 * Handle tiles_invalidated event: refresh MVT cache.
 */
function handleTilesInvalidated() {
  if (window.app) {
    window.app.refreshMVTTiles();
  }
}

/**
 * Disconnect from WebSocket.
 */
export function disconnectDataProcessorWS() {
  if (wsConnection) {
    console.log('[DataWS] Disconnecting...');
    wsConnection.close();
    wsConnection = null;
  }
}

// NOTE: Auto-connect moved to map-main.js (after QWebChannel + window.app init)
