/**
 * MapLibre configuration - colors, styles, and visual settings.
 */

export const MAP_CONFIG = {
  // Initial map settings
  initial: {
    center: [37.6173, 55.7558],  // Moscow center
    zoom: 12,
    minZoom: 0,
    maxZoom: 19,
  },

  // Layer styles
  layers: {
    background: {
      color: '#f3f4f6',
    },

    // Road graph styling (based on OSM highway types)
    graph: {
      colors: {
        motorway: '#1e40af',       // Pink (high-priority highways)
        motorway_link: '#1e40af',
        trunk: '#6200ffff',          // Pale orange
        trunk_link: '#6200ffff',
        primary: '#9c00aaff',        // Light orange
        primary_link: '#9c00aaff',
        secondary: '#ff5effff',      // Yellow
        secondary_link: '#ff5effff',
        tertiary: '#ff2e2eff',       // White
        tertiary_link: '#ff2e2eff',
        residential: '#ff8635ff',    // White
        living_street: '#ff8635ff',  // Light grey
        unclassified: '#5c5c5cff',
        service: '#008d0cff',        // Grey
        default: '#353535ff',        // Dark grey
      },

      // Width multipliers based on lanes (base × multiplier)
      widthByLanes: {
        1: 1.0,
        2: 1.5,
        3: 2.0,
        4: 2.5,
        5: 3.0,
        6: 3.5,
      },

      // Base width by highway type at zoom 15
      baseWidth: {
        motorway: 8,
        trunk: 7,
        primary: 6,
        secondary: 5,
        tertiary: 4,
        residential: 3,
        living_street: 2,
        service: 2,
        default: 2,
      },
    },

    // Route styling
    routes: {
      defaultColor: '#2563eb',
      width: 3,
    },
  },

  // Marker styles
  markers: {
    agent: {
      size: 16,
      color: '#22c55e',
      borderColor: '#065f46',
      borderWidth: 2,
    },
    start: {
      size: 16,
      color: '#ffffff',
      borderColor: '#2563eb',
      borderWidth: 2,
    },
    end: {
      size: 16,
      color: '#ffffff',
      borderColor: '#dc2626',
      borderWidth: 2,
    },
    via: {
      size: 10,
      borderColor: '#000000',
      borderWidth: 2,
    },
  },

  // Animation settings
  animation: {
    agentSmoothing: 0.25,        // Alpha for lerp
    maxFrameDelta: 0.05,         // Max seconds per frame
    zoomDuration: 200,           // ms
    fitBoundsPadding: 40,        // px
    fitBoundsDuration: 400,      // ms
    fitBoundsMaxZoom: 16,
  },

  // Tile configuration
  tiles: {
    tileSize: 256,
    defaultUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  },
};
