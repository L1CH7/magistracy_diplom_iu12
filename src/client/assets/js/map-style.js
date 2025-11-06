/**
 * MapLibre style builder - creates MapLibre GL style object from config.
 */

import { MAP_CONFIG } from './map-config.js';

/**
 * Build MapLibre expression for graph line colors based on highway type.
 */
function buildGraphColorExpression() {
  const colors = MAP_CONFIG.layers.graph.colors;
  return [
    'match',
    ['get', 'highway'],
    ['motorway', 'motorway_link'], colors.motorway,
    ['trunk', 'trunk_link'], colors.trunk,
    ['primary', 'primary_link'], colors.primary,
    ['secondary', 'secondary_link'], colors.secondary,
    ['tertiary', 'tertiary_link'], colors.tertiary,
    ['residential', 'living_street'], colors.residential,
    colors.default,
  ];
}

/**
 * Build MapLibre expression for graph line width based on zoom and highway type.
 */
function buildGraphWidthExpression() {
  const widthCfg = MAP_CONFIG.layers.graph.width;
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    10, widthCfg.zoom10,
    15, [
      'match',
      ['get', 'highway'],
      ['motorway', 'motorway_link'], widthCfg.zoom15.motorway,
      ['trunk', 'trunk_link'], widthCfg.zoom15.trunk,
      ['primary', 'primary_link'], widthCfg.zoom15.primary,
      widthCfg.zoom15.default,
    ],
    18, [
      'match',
      ['get', 'highway'],
      ['motorway', 'motorway_link'], widthCfg.zoom18.motorway,
      ['trunk', 'trunk_link'], widthCfg.zoom18.trunk,
      ['primary', 'primary_link'], widthCfg.zoom18.primary,
      widthCfg.zoom18.default,
    ],
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
    ],
  };
}
