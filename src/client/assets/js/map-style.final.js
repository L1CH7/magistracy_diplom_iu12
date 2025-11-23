/**
 * FINAL: Dynamic LOD layers from YAML with EXACT OLD logic
 */

import { getMapConfig } from './map-config-loader.js';

/**
 * Generate ALL LOD layers dynamically from YAML config.
 * CRITICAL: Uses EXACT same logic as OLD hardcoded version.
 */
function generateAllLodLayers() {
  const MAP_CONFIG = getMapConfig();
  const lodLayers = Array.isArray(MAP_CONFIG.lod) ? MAP_CONFIG.lod : MAP_CONFIG.lod.layers;
  const colors = MAP_CONFIG.layers.graph.colors;
  const widths = MAP_CONFIG.layers.graph.baseWidth;
  
  const result = [];
  
  for (let i = 0; i < lodLayers.length; i++) {
    const lod = lodLayers[i];
    
    // LINE LAYER
    // Build match expression for line-color (or constant for first layer)
    let lineColor;
    if (i === 0) {
      // highways: all motorway/trunk same color → constant
      lineColor = colors['motorway'];
    } else {
      // Build match expression
      const colorPairs = [];
      for (const hw of lod.highways) {
        if (colors[hw]) {
          colorPairs.push(hw, colors[hw]);
        }
      }
      lineColor = ['match', ['get', 'highway'], ...colorPairs, '#353535ff'];
    }
    
    // Build line-width (EXACT OLD logic per layer)
    let lineWidth;
    if (i === 0) {
      // highways
      lineWidth = [
        'interpolate', ['linear'], ['zoom'],
        0, 0.5,
        9, 1.5,
        10, 2
      ];
    } else if (i === 1) {
      // major_roads
      lineWidth = [
        'interpolate', ['linear'], ['zoom'],
        10, 1.5,
        12, 3
      ];
    } else if (i === 2) {
      // arterial_roads
      lineWidth = [
        'interpolate', ['linear'], ['zoom'],
        12, 2,
        14, 4
      ];
    } else {
      // all_roads: 3-point interpolation
      const width15Pairs = [];
      const width18Pairs = [];
      for (const hw of lod.highways) {
        if (widths[hw]) {
          width15Pairs.push(hw, Math.round(widths[hw] * 0.67));
          width18Pairs.push(hw, widths[hw]);
        }
      }
      lineWidth = [
        'interpolate', ['linear'], ['zoom'],
        14, 1.5,
        15, ['match', ['get', 'highway'], ...width15Pairs, 2],
        18, ['match', ['get', 'highway'], ...width18Pairs, 3]
      ];
    }
    
    // Build layer object
    const lineLayer = {
      id: `graph-${lod.name}`,
      type: 'line',
      source: 'graph-vector',
      'source-layer': 'ways',
      minzoom: lod.minzoom,
      filter: ['in', 'highway', ...lod.highways],
      paint: {
        'line-color': lineColor,
        'line-width': lineWidth
      }
    };
    
    // Add maxzoom ONLY if NOT last layer (last layer renders to infinity)
    if (i < lodLayers.length - 1) {
      lineLayer.maxzoom = lod.maxzoom;
    }
    
    result.push(lineLayer);
    
    // LABEL LAYER (if show_names=true)
    if (lod.show_names) {
      const labelLayer = {
        id: `graph-${lod.name}-labels`,
        type: 'symbol',
        source: 'graph-vector',
        'source-layer': 'ways',
        minzoom: 12,  // arterial labels start at 12
        filter: (i === 2)  // arterial: filter to main highways
          ? ['all', ['has', 'name'], ['in', 'highway', 'motorway', 'trunk', 'primary', 'secondary']]
          : ['has', 'name'],
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': (i === 2) ? 11 : ['interpolate', ['linear'], ['zoom'], 12, 10, 18, 14],
          'symbol-placement': 'line',
          'text-font': ['Open Sans Regular']
        },
        paint: {
          'text-color': '#000000',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2
        }
      };
      
      // Add maxzoom ONLY if NOT last layer
      if (i < lodLayers.length - 1) {
        labelLayer.maxzoom = lod.maxzoom;
      }
      
      result.push(labelLayer);
    }
  }
  
  return result;
}

export function createMapStyle(tileUrl) {
  const MAP_CONFIG = getMapConfig();
  if (!MAP_CONFIG) {
    throw new Error('[map-style] Config not loaded!');
  }

  const style = {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
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
      // DYNAMIC LOD LAYERS FROM YAML (using Array.concat())
    ].concat(generateAllLodLayers()).concat([
      // Routes layer
      {
        id: 'routes',
        type: 'line',
        source: 'routes',
        paint: {
          'line-color': MAP_CONFIG.layers.routes.defaultColor,
          'line-width': MAP_CONFIG.layers.routes.width,
        },
      },
      // K-routes layers (inactive border, selected border, assigned border, inactive, selected, assigned)
      {
        id: 'k-routes-inactive-border',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'status'], 'inactive'],
        paint: {
          'line-color': '#ffffff',
          'line-width': MAP_CONFIG.layers.kRoutes.inactive.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.inactive.opacity,
        },
      },
      {
        id: 'k-routes-selected-border',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'status'], 'selected'],
        paint: {
          'line-color': '#ffffff',
          'line-width': MAP_CONFIG.layers.kRoutes.selected.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.selected.opacity,
        },
      },
      {
        id: 'k-routes-assigned-border',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'status'], 'assigned'],
        paint: {
          'line-color': '#ffffff',
          'line-width': MAP_CONFIG.layers.kRoutes.assigned.width + 2,
          'line-opacity': MAP_CONFIG.layers.kRoutes.assigned.opacity,
        },
      },
      {
        id: 'k-routes-inactive',
        type: 'line',
        source: 'k-routes',
        filter: ['==', ['get', 'status'], 'inactive'],
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
        filter: ['==', ['get', 'status'], 'selected'],
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
        filter: ['==', ['get', 'status'], 'assigned'],
        paint: {
          'line-color': MAP_CONFIG.layers.kRoutes.assigned.color,
          'line-width': MAP_CONFIG.layers.kRoutes.assigned.width,
          'line-opacity': MAP_CONFIG.layers.kRoutes.assigned.opacity,
        },
      },
    ]),  // Close concat()
  };

  return style;
}
