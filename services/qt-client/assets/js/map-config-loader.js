/**
 * Map Configuration Loader
 * 
 * Loads map config from Python via QWebChannel (configs/client/map.yaml).
 * Replaces hardcoded MAP_CONFIG from map-config.js.
 */

let MAP_CONFIG = null;
let configLoadPromise = null;

/**
 * Load map config from Python config bridge.
 * @returns {Promise<Object>} Loaded config object
 */
export async function loadMapConfig() {
  if (MAP_CONFIG) {
    return MAP_CONFIG;
  }

  if (configLoadPromise) {
    return configLoadPromise;
  }

  configLoadPromise = new Promise((resolve, reject) => {
    if (!window.globalChannel) {
      reject(new Error('QWebChannel not initialized'));
      return;
    }

    const bridge = window.globalChannel.objects.config_bridge;
    if (!bridge) {
      reject(new Error('config_bridge not found'));
      return;
    }

    bridge.getMapConfig().then(configJson => {
      try {
        const rawConfig = JSON.parse(configJson);

        // Transform YAML config to JS MAP_CONFIG format
        MAP_CONFIG = transformConfig(rawConfig);
        resolve(MAP_CONFIG);
      } catch (error) {
        reject(error);
      }
    }).catch(error => {
      reject(error);
    });
  });

  return configLoadPromise;
}

/**
 * Transform YAML config structure to JS MAP_CONFIG format.
 * Requires COMPLETE config from YAML - no defaults/fallbacks.
 * @param {Object} yaml - Raw config from configs/client/map.yaml
 * @returns {Object} Transformed config
 * @throws {Error} If config is incomplete
 */
function transformConfig(yaml) {
  // Validate required fields (strict validation)
  const required = [
    'rendering', 'lod', 'initial', 'background_color',
    'width_by_lanes', 'routes', 'k_routes', 'markers',
    'animation', 'tiles'
  ];

  for (const field of required) {
    if (!yaml[field]) {
      throw new Error(`[map-config] Missing required field: ${field}`);
    }
  }

  if (!yaml.rendering.colors || !yaml.rendering.widths) {
    throw new Error('[map-config] Missing rendering.colors or rendering.widths');
  }

  if (!yaml.lod.layers || !Array.isArray(yaml.lod.layers)) {
    throw new Error('[map-config] Missing or invalid lod.layers');
  }

  // Return config directly from YAML (NO hardcoded defaults)
  // Also inject apiBaseUrl from the bridge (not in YAML but needed by JS)
  const config = {
    initial: yaml.initial,
    style: yaml.style,

    layers: {
      background: {
        color: yaml.background_color,
      },

      graph: {
        colors: yaml.rendering.colors,
        widthByLanes: yaml.width_by_lanes,
        baseWidth: yaml.rendering.widths,
      },

      routes: yaml.routes,
      kRoutes: yaml.k_routes,
    },

    markers: yaml.markers,
    animation: yaml.animation,
    tiles: yaml.tiles,
    lod: yaml.lod.layers,
    apiBaseUrl: yaml.apiBaseUrl || 'http://localhost:8000' // Fallback
  };

  return config;
}

/**
 * Get current map config (sync, must be loaded first).
 * @returns {Object|null} Config object or null if not loaded
 */
export function getMapConfig() {
  return MAP_CONFIG;
}
