/**
 * MapLibre style builder - creates MapLibre GL style object from config.
 */

import { MAP_CONFIG } from './map-config.js';

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
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: MAP_CONFIG.tiles.tileSize,
      },
      graph: {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
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
      {
        id: 'graph',
        type: 'line',
        source: 'graph',
        paint: {
          'line-color': buildGraphColorExpression(),
          'line-width': buildGraphWidthExpression(),
        },
      },
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
}
