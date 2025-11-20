/**
 * WebSocket Client for tile update notifications from Data Processor.
 * 
 * Connects to ws://localhost:8005/api/v1/ws/tile-updates
 * Receives notifications when OSM tiles finish downloading.
 * Automatically refreshes affected MVT tiles.
 */

let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_DELAY = 5000; // 5 seconds

function logToConsole(message) {
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    console.log(message);
  }
}

/**
 * Connect to WebSocket server.
 */
function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return; // Already connected or connecting
  }

  const wsUrl = 'ws://localhost:8005/api/v1/ws/tile-updates';
  logToConsole(`[WS] Connecting to ${wsUrl}...`);

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    logToConsole('[WS] Connected to Data Processor');
    reconnectAttempts = 0; // Reset reconnect counter
    
    // Send keepalive ping every 30 seconds
    setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping');
      }
    }, 30000);
  };

  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      handleMessage(message);
    } catch (error) {
      console.error('[WS] Failed to parse message:', error);
    }
  };

  ws.onerror = (error) => {
    logToConsole('[WS] Connection error');
  };

  ws.onclose = () => {
    logToConsole('[WS] Connection closed, will retry...');
    scheduleReconnect();
  };
}

/**
 * Schedule reconnect attempt.
 */
function scheduleReconnect() {
  if (reconnectTimer) {
    return; // Already scheduled
  }

  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    logToConsole('[WS] Max reconnect attempts reached, giving up');
    return;
  }

  reconnectAttempts++;
  const delay = RECONNECT_DELAY * reconnectAttempts; // Exponential backoff
  logToConsole(`[WS] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempts})`);

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectWebSocket();
  }, delay);
}

/**
 * Handle incoming WebSocket message.
 */
function handleMessage(message) {
  if (message.type === 'tiles_ready') {
    const tiles = message.tiles || [];
    const osmTile = message.osm_tile || {};
    
    logToConsole(
      `[WS] Tiles ready: OSM [${osmTile.lon?.toFixed(2)}, ${osmTile.lat?.toFixed(2)}], ` +
      `${tiles.length} MVT tiles affected`
    );
    
    // Refresh MVT tiles
    if (window.app && typeof window.app.refreshMVTTiles === 'function') {
      window.app.refreshMVTTiles();
      logToConsole('[WS] MVT tiles refreshed');
    } else {
      console.warn('[WS] window.app.refreshMVTTiles() not available');
    }
  }
}

/**
 * Disconnect WebSocket.
 */
function disconnectWebSocket() {
  if (ws) {
    ws.close();
    ws = null;
  }
  
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

// WebSocket disabled: endpoint /api/v1/ws/tile-updates not implemented yet
// Auto-connect when page loads
// if (document.readyState === 'loading') {
//   document.addEventListener('DOMContentLoaded', () => {
//     setTimeout(connectWebSocket, 1000); // Connect after 1s delay
//   });
// } else {
//   setTimeout(connectWebSocket, 1000);
// }

// Export for manual control
window.wsClient = {
  connect: connectWebSocket,
  disconnect: disconnectWebSocket
};

console.log('[ws-client.js] WebSocket client initialized');
