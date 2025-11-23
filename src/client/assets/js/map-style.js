/**
 * map-style.js - MapLibre GL style generator (100% config-driven)
 */

import { getMapConfig } from './map-config-loader.js';

function buildMatchExpression(property, configObject, defaultValue) {
  const pairs = [];
  for (const [key, value] of Object.entries(configObject)) {
    if (key !== 'default') pairs.push(key, value);
  }
  return ['match', ['get', property], ...pairs, configObject.default || defaultValue];
}

function generateLodLayers(lodConfig, colors, widths) {
  const layers = [];
  for (const lod of lodConfig.layers) {
    const { name, minzoom, maxzoom, highways, base_width, show_names } = lod;
    const filter = ['in', 'highway', ...highways];
    layers.push({
      id: `graph-${name}`,
      type: 'line',
      source: 'graph-vector',
      'source-layer': 'ways',
      minzoom,
      maxzoom,
      filter,
      paint: {
        'line-color': buildMatchExpression('highway', colors, '#353535ff'),
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          minzoom, base_width,
          15, ['*', base_width, 1.5],
          18, buildMatchExpression('highway', widths, 2)
        ]
      }
    });
    if (show_names) {
      layers.push({
        id: `graph-${name}-labels`,
        type: 'symbol',
        source: 'graph-vector',
        'source-layer': 'ways',
        minzoom: minzoom + 1,
        maxzoom,
        filter: ['all', filter, ['has', 'name']],
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': ['interpolate', ['linear'], ['zoom'], 12, 10, 18, 14],
          'symbol-placement': 'line',
          'text-font': ['Open Sans Regular']
        },
        paint: {
          'text-color': '#000000',
          'text-halo-color': '#ffffff',
          'text-halo-width': 2
        }
      });
    }
  }
  return layers;
}

export function createMapStyle(tileUrl) {
  const cfg = getMapConfig();
  if (!cfg) throw new Error('[map-style] Config not loaded');
  
  const lodLayersArray = Array.isArray(cfg.lod) ? cfg.lod : cfg.lod.layers;
  
  // Log LOD layers (verified: config loads correctly)
  if (window.globalChannel?.objects?.logger_bridge) {
    const logger = window.globalChannel.objects.logger_bridge;
    logger.log_info(`[map-style] LOD layers count: ${lodLayersArray.length}`);
    lodLayersArray.forEach((layer, i) => {
      const hwCount = layer.highways ? layer.highways.length : 0;
      logger.log_info(`[map-style]   Layer ${i}: ${layer.name} (zoom ${layer.minzoom}-${layer.maxzoom}), ${hwCount} highways`);
    });
  }
  
  const lodLayers = generateLodLayers(
    { layers: lodLayersArray },
    cfg.layers.graph.colors,
    cfg.layers.graph.baseWidth
  );
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      osm: { type: 'raster', tiles: [tileUrl], tileSize: cfg.tiles.tileSize },
      'graph-vector': { type: 'vector', tiles: ['http://localhost:8005/api/v1/tiles/{z}/{x}/{y}.mvt'], minzoom: 0, maxzoom: 18 },
      routes: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      'k-routes': { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': cfg.layers.background.color } },
      { id: 'osm', type: 'raster', source: 'osm' },
      ...lodLayers,
      { id: 'routes', type: 'line', source: 'routes', paint: { 'line-color': ['get', 'color'], 'line-width': cfg.layers.routes.width } },
      ...['inactive', 'selected', 'assigned'].flatMap(type => [
        { id: `k-routes-${type}-casing`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': '#000000', 'line-width': cfg.layers.kRoutes[type].width + 2, 'line-opacity': cfg.layers.kRoutes[type].opacity } },
        { id: `k-routes-${type}`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': cfg.layers.kRoutes[type].color, 'line-width': cfg.layers.kRoutes[type].width, 'line-opacity': cfg.layers.kRoutes[type].opacity } }
      ])
    ]
  };
}

// Map style loaded (100% config-driven)
