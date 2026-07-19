/**
 * map-style.js - MapLibre GL style generator (100% config-driven)
 */

import { getMapConfig } from './map-config-loader.js';

function generateLodLayers(lodConfig, colors, widths, includeLabels = true) {
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

    const config = getMapConfig();
    const visualizationModes = (config && config.visualizationModes) || ['highway_type'];
    const isHeatmapEnabled = visualizationModes.includes('traffic_load');
    const capacityOverloadK = (config && config.trafficHeatmap && config.trafficHeatmap.capacity_overload_k) || 2.0;
    
    const fallbackColor = ['match', ['get', 'highway']];
    for (const [hwType, hwColor] of Object.entries(colors || {})) {
      fallbackColor.push(hwType, hwColor);
    }
    fallbackColor.push('#333333'); // Default fallback

    const trafficLoadColorExpression = [
        'let',
        'ratio', ['/', 
            ['coalesce', ['feature-state', 'volume'], 0], 
            ['max', ['coalesce', ['feature-state', 'capacity'], 1], 1]
        ],
        ['case',
            ['>', ['coalesce', ['feature-state', 'volume'], 0], 0],
            ['interpolate',
                ['linear'],
                ['var', 'ratio'],
                0.0, 'hsla(120, 100%, 50%, 0.95)',
                0.3, 'hsla(60, 100%, 50%, 0.95)',
                0.6, 'hsla(30, 100%, 50%, 0.95)',
                1.0, 'hsla(0, 100%, 50%, 0.95)',
                capacityOverloadK, 'hsla(0, 0%, 0%, 0.95)'
            ],
            isHeatmapEnabled ? 'hsla(120, 100%, 50%, 0.95)' : fallbackColor
        ]
    ];

    const mainColorExpression = isHeatmapEnabled ? trafficLoadColorExpression : fallbackColor;

    // Build line-width based on per-highway target width
    const baseWidth = lod.base_width || 1.0;
    const highwayWidthMatch = ['match', ['get', 'highway']];
    for (const hw of highways) {
      highwayWidthMatch.push(hw, widths[hw] || widths.default || 1.0);
    }
    highwayWidthMatch.push(1.0); // Default multiplier
    
    // Casing layer for contrast (rendered under the main layer)
    const casingLayerDef = {
      id: `graph-${name}-casing`,
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
        'line-color': '#111111',
        'line-opacity': [
            'case',
            ['>', ['coalesce', ['feature-state', 'volume'], 0], 0],
            0.8,
            0.0
        ],
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          minzoom, ['+', ['*', baseWidth, 1.2], 1.5],
          18, ['+', ['*', highwayWidthMatch, 1.5 * 1.2], 2.0]
        ]
      }
    };
    layers.push(casingLayerDef);

    // 1. Base layer (colored by feature-state)
    const baseLayerDef = {
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
        'line-color': mainColorExpression,
        'line-width': [
          'interpolate', ['linear'], ['zoom'],
          minzoom, [
            'case',
            ['>', ['coalesce', ['feature-state', 'volume'], 0], 0],
            ['*', baseWidth, 1.2],
            baseWidth
          ],
          18, [
            'case',
            ['>', ['coalesce', ['feature-state', 'volume'], 0], 0],
            ['*', highwayWidthMatch, 1.5 * 1.2],
            ['*', highwayWidthMatch, 1.5]
          ]
        ]
      }
    };
    layers.push(baseLayerDef);

    if (show_names && includeLabels) {
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

export function getBaseStyle() {
  const cfg = getMapConfig();
  if (!cfg) throw new Error('[map-style] Config not loaded');

  const lodLayersArray = Array.isArray(cfg.lod) ? cfg.lod : cfg.lod.layers;

  // Generate vector layers WITHOUT labels initially
  const lodLayers = generateLodLayers(
    { layers: lodLayersArray },
    cfg.layers.graph.colors,
    cfg.rendering?.widths || cfg.layers.graph.baseWidth,
    false
  );

  return {
    version: 8,
    glyphs: 'http://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      'graph-vector': {
        type: 'vector',
        tiles: [`${cfg.apiBaseUrl || 'http://localhost:8000'}/tiles/{z}/{x}/{y}.mvt?v=${Date.now()}`],
        minzoom: 0,
        maxzoom: (cfg.tiles && cfg.tiles.maxZoom) ? cfg.tiles.maxZoom : 14
      },
      routes: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      'k-routes': { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': cfg.layers.background.color || '#f3f4f6' } },
    ].concat(lodLayers).concat([
      { id: 'routes', type: 'line', source: 'routes', paint: { 'line-color': ['get', 'color'], 'line-width': cfg.layers.routes.width } }
    ]).concat(['inactive', 'selected', 'assigned'].flatMap(type => [
      { id: `k-routes-${type}-casing`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': '#000000', 'line-width': (cfg.layers.kRoutes[type]?.width || 3) + 2, 'line-opacity': cfg.layers.kRoutes[type]?.opacity || 0.6 } },
      { id: `k-routes-${type}`, type: 'line', source: 'k-routes', filter: type === 'inactive' ? ['!=', ['get', 'route_id'], -1] : ['==', ['get', 'route_id'], -1], paint: { 'line-color': cfg.layers.kRoutes[type]?.color || '#3b82f6', 'line-width': cfg.layers.kRoutes[type]?.width || 3, 'line-opacity': cfg.layers.kRoutes[type]?.opacity || 1.0 } }
    ]))
  };
}

export function addOsmRaster(map, tileUrl, tileSize = 256) {
  if (map.getSource('osm')) return;
  
  map.addSource('osm', {
    type: 'raster',
    tiles: [tileUrl],
    tileSize: tileSize,
    attribution: '&copy; OpenStreetMap contributors'
  });

  const layers = map.getStyle().layers;
  const firstNonBackground = layers.find(l => l.id !== 'background');

  map.addLayer({
    id: 'osm',
    type: 'raster',
    source: 'osm',
    paint: {
      'raster-opacity': 1.0,
      'raster-fade-duration': 300
    }
  }, firstNonBackground ? firstNonBackground.id : undefined);
}

export function addRoadLabels(map, glyphsUrl) {
  const cfg = getMapConfig();
  if (!cfg) return;

  if (glyphsUrl) {
    map.setGlyphs(glyphsUrl);
  }

  const lodLayersArray = Array.isArray(cfg.lod) ? cfg.lod : cfg.lod.layers;
  
  // Generate ONLY label layers
  const labelLayers = generateLodLayers(
    { layers: lodLayersArray },
    cfg.layers.graph.colors,
    cfg.rendering?.widths || cfg.layers.graph.baseWidth,
    true
  ).filter(l => l.type === 'symbol');

  labelLayers.forEach(layer => {
    if (!map.getLayer(layer.id)) {
      map.addLayer(layer);
    }
  });
}
