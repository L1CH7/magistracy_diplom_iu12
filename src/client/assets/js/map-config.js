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

    // Road graph styling
    graph: {
      colors: {
        motorway: '#1e40af',      // Dark blue
        trunk: '#1e3a8a',         // Navy blue
        primary: '#1d4ed8',       // Blue
        secondary: '#2563eb',     // Medium blue
        tertiary: '#3b82f6',      // Light blue
        residential: '#60a5fa',   // Very light blue
        living_street: '#60a5fa',
        default: '#93c5fd',       // Pale blue
      },

      // Width configuration by zoom and highway type
      width: {
        // Base width at zoom 10
        zoom10: 1,
        // Width at zoom 15 by highway type
        zoom15: {
          motorway: 3,
          trunk: 2.5,
          primary: 2,
          default: 1.5,
        },
        // Width at zoom 18 by highway type
        zoom18: {
          motorway: 6,
          trunk: 5,
          primary: 4,
          default: 3,
        },
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
