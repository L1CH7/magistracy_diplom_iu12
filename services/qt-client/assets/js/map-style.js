/**
 * map-style.js - MapLibre GL style generator (100% config-driven)
 */

import { getMapConfig } from './map-config-loader.js';

function generateLodLayers(lodConfig, colors, widths) {
  const layers = [];
  for (const lod of lodConfig.layers) {
    const { name, minzoom, maxzoom, highways, show_names } = lod;

    // Build filter from highways list
    const filter = (highways && highways.length > 0) ? ['in', 'highway', ...highways] : null;

    // DEBUG
    if (window.globalChannel?.objects?.logger_bridge) {
      const logger = window.globalChannel.objects.logger_bridge;
      logger.log_info(`[LOD] ${name}: z${minzoom}-${maxzoom}, highways: ${highways?.length || 0}`);
    }

    // Build color pairs
    const colorPairs = [];
    for (const hw of highways) {
      if (colors[hw]) {
        colorPairs.push(hw, colors[hw]);
      }
    }

    const colorExpression = ['match', ['get', 'highway'], ...colorPairs, '#353535ff'];

    // Build line-width based on LOD base_width
    let widthExpression;
    const baseWidth = lod.base_width || 1.0;

    // Smooth interpolation for the layer duration
    // We assume the base_width is the target width at the START of the zoom range
    // And we scale it up slightly towards the end
    widthExpression = [
      'interpolate', ['linear'], ['zoom'],
      minzoom, baseWidth,
      maxzoom, baseWidth * 2.0
    ];

    const layerDef = {
      id: `graph-${name}`,
      type: 'line',
      source: 'graph-vector',
      'source-layer': 'ways',
      minzoom,
      ...(maxzoom !== undefined && maxzoom !== null ? { maxzoom } : {}),
      ...(filter !== null ? { filter } : {}),
      layout: {
        'line-join': 'round',
        'line-cap': 'round'
      },
      paint: {
        'line-color': colorExpression,
        'line-width': widthExpression
      }
    };

    layers.push(layerDef);

    if (show_names) {
      const labelFilter = ['has', 'name'];

      layers.push({
        id: `graph-${name}-labels`,
        type: 'symbol',
        source: 'graph-vector',
        'source-layer': 'ways',
        minzoom: Math.max(minzoom, 12),
        ...(maxzoom !== undefined && maxzoom !== null ? { maxzoom } : {}),
        filter: labelFilter,
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': 12,
          'symbol-placement': 'line'
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

  const lodLayers = generateLodLayers(
    { layers: lodLayersArray },
    cfg.layers.graph.colors,
    cfg.rendering?.widths || cfg.layers.graph.baseWidth
  );

  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      osm: { type: 'raster', tiles: [tileUrl], tileSize: cfg.tiles.tileSize },
      'graph-vector': {
        type: 'vector',
        tiles: [`${cfg.apiBaseUrl || 'http://localhost:8000'}/tiles/{z}/{x}/{y}.mvt?v=${Date.now()}`],
        minzoom: 0,
        maxzoom: 18
      },
      routes: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      'k-routes': { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': cfg.layers.background.color } },
      { id: 'osm', type: 'raster', source: 'osm' },
    ].concat(lodLayers).concat([
      { id: 'routes', type: 'line', source: 'routes', paint: { 'line-color': ['get', 'color'], 'line-width': cfg.layers.routes.width } }
    ]).concat(['inactive', 'selected', 'assigned'].flatMap(type => [
      { id: `k-routes-${type}-casing`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': '#000000', 'line-width': cfg.layers.kRoutes[type].width + 2, 'line-opacity': cfg.layers.kRoutes[type].opacity } },
      { id: `k-routes-${type}`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': cfg.layers.kRoutes[type].color, 'line-width': cfg.layers.kRoutes[type].width, 'line-opacity': cfg.layers.kRoutes[type].opacity } }
    ]))
  };
}
