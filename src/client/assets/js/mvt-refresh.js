/**
 * MVT Tile Auto-Refresh
 * 
 * Periodically checks if new OSM data has been loaded and refreshes MVT tiles.
 * Solves the problem of cached empty tiles when data is loaded progressively.
 */

let lastWayCount = 0;
let refreshCheckInterval = null;

/**
 * Query database for current way count via Data Processor API.
 */
async function getWayCount() {
  try {
    const response = await fetch('http://localhost:8005/api/v1/status');
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

/**
 * Check if new data is available and refresh tiles if needed.
 */
async function checkAndRefresh() {
  if (!window.app || !window.map) {
    console.log('[MVT-Refresh] Waiting for map initialization...');
    return;
  }

  const currentCount = await getWayCount();
  if (currentCount === null) {
    // API not available or error
    return;
  }

  if (currentCount > lastWayCount) {
    console.log(
      `[MVT-Refresh] New data detected: ${lastWayCount} → ${currentCount} ways, ` +
      'refreshing tiles...'
    );
    
    // Refresh MVT tiles
    window.app.refreshMVTTiles();
    lastWayCount = currentCount;
    
    // Log to Python if bridge available
    if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
      window.globalChannel.objects.logger_bridge.log_info(
        `[MVT-Refresh] Updated tiles (${currentCount} ways)`
      );
    }
  }
}

/**
 * Start periodic refresh checks.
 * @param {number} intervalMs - Check interval in milliseconds (default: 10000)
 */
export function startMVTRefresh(intervalMs = 10000) {
  if (refreshCheckInterval) {
    console.log('[MVT-Refresh] Already running');
    return;
  }

  console.log(`[MVT-Refresh] Starting auto-refresh (interval: ${intervalMs}ms)`);
  
  // Initial check
  checkAndRefresh();
  
  // Periodic checks
  refreshCheckInterval = setInterval(checkAndRefresh, intervalMs);
}

/**
 * Stop periodic refresh checks.
 */
export function stopMVTRefresh() {
  if (refreshCheckInterval) {
    clearInterval(refreshCheckInterval);
    refreshCheckInterval = null;
    console.log('[MVT-Refresh] Stopped auto-refresh');
  }
}

// Auto-start when loaded
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => startMVTRefresh(), 2000);  // Start after 2s delay
  });
} else {
  setTimeout(() => startMVTRefresh(), 2000);
}
