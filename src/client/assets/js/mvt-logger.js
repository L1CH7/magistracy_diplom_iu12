/**
 * MVT Request Logger - MUST be loaded BEFORE map-main.js!
 * Intercepts XHR and fetch to log MVT tile requests.
 */

// Helper function to log to Python via QWebChannel
function logMVTRequest(z, x, y) {
  const message = `[MVT] Requesting tile [${z}/${x}/${y}] from Data Processor`;
  
  if (window.globalChannel && window.globalChannel.objects.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(message);
  } else {
    // Fallback to console if bridge not ready
    console.log(message);
  }
}

// Intercept XMLHttpRequest (MapLibre uses XHR for MVT!)
const originalXHROpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(method, url, ...rest) {
  if (typeof url === 'string' && url.includes('/tiles/')) {
    const match = url.match(/\/tiles\/(\d+)\/(\d+)\/(\d+)\.mvt/);
    if (match) {
      const [, z, x, y] = match;
      logMVTRequest(z, x, y);
    }
  }
  return originalXHROpen.apply(this, [method, url, ...rest]);
};

// Intercept fetch (backup)
const originalFetch = window.fetch;
window.fetch = function(...args) {
  const url = args[0];
  if (typeof url === 'string' && url.includes('/tiles/')) {
    const match = url.match(/\/tiles\/(\d+)\/(\d+)\/(\d+)\.mvt/);
    if (match) {
      const [, z, x, y] = match;
      logMVTRequest(z, x, y);
    }
  }
  return originalFetch.apply(this, args);
};

console.log('[mvt-logger.js] MVT request logging initialized');
