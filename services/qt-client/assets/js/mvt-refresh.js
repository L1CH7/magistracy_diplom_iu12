/**
 * MVT Tile Refresh API
 * 
 * Manual refresh function for MVT tiles.
 * Auto-refresh is now handled by data-ws-client.js (WebSocket events).
 */

/**
 * Manually refresh MVT tiles.
 * Called by WebSocket client when new data is available.
 */
export function refreshMVTTiles() {
  if (!window.app || !window.map) {
    console.warn('[MVT-Refresh] Map not initialized, skipping refresh');
    return;
  }

  console.log('[MVT-Refresh] Refreshing MVT tiles...');

  // Trigger map refresh
  window.app.refreshMVTTiles();

  // Log to Python if bridge available
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(
      '[MVT-Refresh] Tiles refreshed'
    );
  }
}

/**
 * Get current way count from Data Processor API.
 * Used for debugging/stats display.
 */
export async function getWayCount() {
  try {
    // Use configured API URL
    const baseUrl = (window.MAP_CONFIG && window.MAP_CONFIG.apiBaseUrl) || 'http://localhost:8000';
    const response = await fetch(`${baseUrl}/status`);
    if (!response.ok) {
      return null;
    }
    const stats = await response.json();
    return stats.database?.ways || 0;
  } catch (error) {
    console.log('[MVT-Refresh] Failed to fetch stats:', error.message);
    return null;
  }
}
