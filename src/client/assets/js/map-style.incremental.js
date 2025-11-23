/**
 * MapLibre style builder - creates MapLibre GL style object from config.
 * 
 * Config is loaded from configs/client/map.yaml via Python bridge.
 */

import { getMapConfig } from './map-config-loader.js';

/**
 * Build MapLibre expression for graph line colors based on OSM highway type.
 */
function buildGraphColorExpression() {
  const colors = MAP_CONFIG.layers.graph.colors;
  return [
    'match',
    ['get', 'highway'],
    'motorway', colors.motorway,
    'motorway_link', colors.motorway_link,
    'trunk', colors.trunk,
    'trunk_link', colors.trunk_link,
    'primary', colors.primary,
    'primary_link', colors.primary_link,
    'secondary', colors.secondary,
    'secondary_link', colors.secondary_link,
    'tertiary', colors.tertiary,
    'tertiary_link', colors.tertiary_link,
    'residential', colors.residential,
    'living_street', colors.living_street,
    'unclassified', colors.unclassified,
    'service', colors.service,
    colors.default,
  ];
}

/**
 * Build MapLibre expression for graph line width.
 * Considers: zoom level, highway type, and lane count from OSM.
 */
function buildGraphWidthExpression() {
  const baseWidth = MAP_CONFIG.layers.graph.baseWidth;
  const laneMultipliers = MAP_CONFIG.layers.graph.widthByLanes;

  // Get base width by highway type
  const baseByType = [
    'match',
    ['get', 'highway'],
    'motorway', baseWidth.motorway,
    'motorway_link', baseWidth.motorway,
    'trunk', baseWidth.trunk,
    'trunk_link', baseWidth.trunk,
    'primary', baseWidth.primary,
    'primary_link', baseWidth.primary,
    'secondary', baseWidth.secondary,
    'secondary_link', baseWidth.secondary,
    'tertiary', baseWidth.tertiary,
    'tertiary_link', baseWidth.tertiary,
    'residential', baseWidth.residential,
    'living_street', baseWidth.living_street,
    'service', baseWidth.service,
    baseWidth.default,
  ];

  // Multiply by lane count (if available)
  const withLanes = [
    '*',
    baseByType,
    [
      'match',
      ['to-number', ['get', 'lanes'], 1],
      1, laneMultipliers[1],
      2, laneMultipliers[2],
      3, laneMultipliers[3],
      4, laneMultipliers[4],
      5, laneMultipliers[5],
      6, laneMultipliers[6],
      laneMultipliers[2], // default: 2 lanes
    ],
  ];

  // Scale by zoom
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    10, ['*', withLanes, 0.3],  // Thin at low zoom
    15, withLanes,               // Base width at zoom 15
    18, ['*', withLanes, 1.5],   // Thicker at high zoom
  ];
}

/**
 * Create MapLibre GL style object.
 * @param {string} tileUrl - URL template for raster tiles
 */
export function createMapStyle(tileUrl) {
  const MAP_CONFIG = getMapConfig();
  if (!MAP_CONFIG) {
    throw new Error('[map-style] Config not loaded! Call loadMapConfig() first');
  }

  const style = {
    version: MAP_CONFIG.style.version,
    glyphs: MAP_CONFIG.style.glyphs,
    sources: {
      osm: {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: MAP_CONFIG.tiles.tileSize,
      },
      'graph-vector': {
        type: 'vector',
        tiles: ['http://localhost:8005/api/v1/tiles/{z}/{x}/{y}.mvt'],
        minzoom: 0,
        maxzoom: 18
      },
      routes: {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      },
      'k-routes': {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      },
    },
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: {
          'background-color': MAP_CONFIG.layers.background.color,
        },
      },
      {
        id: 'osm',
        type: 'raster',
        source: 'osm',
      },
      // LOD Layer 1: Motorways (zoom 0-9.99) - FROM YAML CONFIG
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[0];  // highways
        return {
          id: `graph-${lod.name}`,
          type: 'line',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
          filter: ['in', 'highway', ...lod.highways],
          paint: {
            'line-color': MAP_CONFIG.layers.graph.colors['motorway'],
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              0, 0.5,
              9, 1.5,
              10, 2
            ]
          }
        };
      })(),
      // LOD Layer 2: Major roads (zoom 10-11.99) - FROM YAML CONFIG
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[1];  // major_roads
        const colors = MAP_CONFIG.layers.graph.colors;
        
        // Build match expression for line-color
        const colorPairs = [];
        for (const hw of lod.highways) {
          if (colors[hw]) {
            colorPairs.push(hw, colors[hw]);
          }
        }
        
        return {
          id: `graph-${lod.name}`,
          type: 'line',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
          filter: ['in', 'highway', ...lod.highways],
          paint: {
            'line-color': ['match', ['get', 'highway'], ...colorPairs, '#353535ff'],
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              10, 1.5,
              12, 3
            ]
          }
        };
      })(),
      // LOD Layer 3: Arterial roads (zoom 12-13.99) - FROM YAML CONFIG
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[2];  // arterial_roads
        const colors = MAP_CONFIG.layers.graph.colors;
        
        // Build match expression for line-color
        const colorPairs = [];
        for (const hw of lod.highways) {
          if (colors[hw]) {
            colorPairs.push(hw, colors[hw]);
          }
        }
        
        return {
          id: `graph-${lod.name}`,
          type: 'line',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
          filter: ['in', 'highway', ...lod.highways],
          paint: {
            'line-color': ['match', ['get', 'highway'], ...colorPairs, '#353535ff'],
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              lod.minzoom, 2,
              lod.maxzoom, 4
            ]
          }
        };
      })(),
      // LOD Layer 4: All roads (zoom >= 14) - FROM YAML CONFIG (NO MAXZOOM!)
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[3];  // all_roads
        const colors = MAP_CONFIG.layers.graph.colors;
        const widths = MAP_CONFIG.layers.graph.baseWidth;  // baseWidth = rendering.widths object
        
        // Build match expression for line-color (ALL 14 types)
        const colorPairs = [];
        for (const hw of lod.highways) {
          if (colors[hw]) {
            colorPairs.push(hw, colors[hw]);
          }
        }
        
        // Build match expression for line-width at zoom 15
        const width15Pairs = [];
        for (const hw of lod.highways) {
          if (widths[hw]) {
            // Scale by factor (15 vs 18): zoom 15 uses ~2/3 of zoom 18 width
            width15Pairs.push(hw, Math.round(widths[hw] * 0.67));
          }
        }
        
        // Build match expression for line-width at zoom 18
        const width18Pairs = [];
        for (const hw of lod.highways) {
          if (widths[hw]) {
            width18Pairs.push(hw, widths[hw]);
          }
        }
        
        return {
          id: `graph-${lod.name}`,
          type: 'line',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
          filter: ['in', 'highway', ...lod.highways],
          // NO MAXZOOM - renders to infinity!
          paint: {
            'line-color': ['match', ['get', 'highway'], ...colorPairs, '#353535ff'],
            'line-width': [
              'interpolate', ['linear'], ['zoom'],
              lod.minzoom, 1.5,
              15, ['match', ['get', 'highway'], ...width15Pairs, 2],
              18, ['match', ['get', 'highway'], ...width18Pairs, 3]
            ]
          }
        };
      })(),
      // MVT Labels: Arterial roads (FROM YAML)
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[2];  // arterial_roads
        if (window.globalChannel?.objects?.logger_bridge) {
          window.globalChannel.objects.logger_bridge.log_info(
            `[incremental] arterial labels: lod.minzoom=${lod.minzoom}, lod.maxzoom=${lod.maxzoom}`
          );
        }
        return {
          id: `graph-${lod.name}-labels`,
          type: 'symbol',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
        filter: [
          'all',
          ['has', 'name'],
          ['in', 'highway', 
            'motorway', 'motorway_link', 
            'trunk', 'trunk_link', 
            'primary', 'primary_link', 
            'secondary', 
            'secondary_link', 
            'tertiary', 'tertiary_link', 
            'residential']
        ],
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': 11,
          'symbol-placement': 'line',
        },
        paint: {
          'text-color': '#000000',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2
        }
        };
      })(),
      // MVT Labels: All roads (FROM YAML)
      (() => {
        const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
        const lod = lodLayers[3];  // all_roads
        return {
          id: `graph-${lod.name}-labels`,
          type: 'symbol',
          source: 'graph-vector',
          'source-layer': 'ways',
          minzoom: lod.minzoom,
          maxzoom: lod.maxzoom,
        filter: ['has', 'name'],
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': 12,
          'symbol-placement': 'line',
        },
        paint: {
          'text-color': '#000000',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2
        }
        };
      })(),
      {
        id: 'routes',
        type: 'line',
        source: 'routes',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': MAP_CONFIG.layers.routes.width,
        },
      },
      // K routes with black borders: Gray (all) < Blue (selected) < Green (assigned)
      // Casing layers first (black borders)
      {
        id: 'k-routes-inactive-casing',
        type: 'line',
        source: 'k-routes',
        filter: ['!=', ['get', 'route_id'], -1],
        paint: {
          'line-color': '#000000',
          'line-width': MAP_CONFIG.layers.kRoutes.inactive.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.inactive.opacity,
        },
      },
      {
        id: 'k-routes-selected-casing',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'route_id'], -1],
        paint: {
          'line-color': '#000000',
          'line-width': MAP_CONFIG.layers.kRoutes.selected.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.selected.opacity,
        },
      },
      {
        id: 'k-routes-assigned-casing',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'route_id'], -1],
        paint: {
          'line-color': '#000000',
          'line-width': MAP_CONFIG.layers.kRoutes.assigned.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.assigned.opacity,
        },
      },
      // Main color layers
      {
        id: 'k-routes-inactive',
        type: 'line',
        source: 'k-routes',
        filter: ['!=', ['get', 'route_id'], -1],  // Will be updated dynamically
        paint: {
          'line-color': MAP_CONFIG.layers.kRoutes.inactive.color,
          'line-width': MAP_CONFIG.layers.kRoutes.inactive.width,
          'line-opacity': MAP_CONFIG.layers.kRoutes.inactive.opacity,
        },
      },
      {
        id: 'k-routes-selected',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'route_id'], -1],  // Will be updated dynamically
        paint: {
          'line-color': MAP_CONFIG.layers.kRoutes.selected.color,
          'line-width': MAP_CONFIG.layers.kRoutes.selected.width,
          'line-opacity': MAP_CONFIG.layers.kRoutes.selected.opacity,
        },
      },
      {
        id: 'k-routes-assigned',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'route_id'], -1],  // Will be updated dynamically
        paint: {
          'line-color': MAP_CONFIG.layers.kRoutes.assigned.color,
          'line-width': MAP_CONFIG.layers.kRoutes.assigned.width,
          'line-opacity': MAP_CONFIG.layers.kRoutes.assigned.opacity,
        },
      },
    ],
  };
  
  // DEBUG: Dump OLD style to JSON (save to .trash/)
  return style;
}
