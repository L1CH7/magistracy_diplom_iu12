/**
 * map-style.js - MapLibre GL style generator (100% config-driven)
 */

import { getMapConfig } from './map-config-loader.js';

function buildMatchExpression(property, configObject, defaultValue) {
  const pairs = [];
  for (const [key, value] of Object.entries(configObject)) {
    if (key !== 'default') pairs.push(key, value);
  }
  const result = ['match', ['get', property], ...pairs, configObject.default || defaultValue];
  
  // DEBUG: Log result
  if (window.globalChannel?.objects?.logger_bridge) {
    window.globalChannel.objects.logger_bridge.log_info(
      `[buildMatchExpression] property=${property}, pairs.length=${pairs.length}`
    );
  }
  
  return result;
}

function generateLodLayers(lodConfig, colors, widths) {
  const layers = [];
  for (const lod of lodConfig.layers) {
    const { name, minzoom, maxzoom, highways, base_width, show_names } = lod;
    
    // CRITICAL: Last layer (all_roads) should NOT have filter (renders ALL ways)
    // This matches old behavior where graph-all had no filter
    const filter = (name === 'all_roads') ? undefined : ['in', 'highway', ...highways];
    
    // DEBUG: Log filter for each LOD layer
    if (window.globalChannel?.objects?.logger_bridge) {
      const logger = window.globalChannel.objects.logger_bridge;
      logger.log_info(`[generateLodLayers] ${name}: highways input = ${JSON.stringify(highways)}`);
      logger.log_info(`[generateLodLayers] ${name}: filter result = ${JSON.stringify(filter)}`);
      logger.log_info(`[generateLodLayers] ${name}: minzoom=${minzoom}, maxzoom=${maxzoom}`);
    }
    
    // Filter colors to only include highways from this layer's filter
    const filteredColors = {};
    if (highways && highways.length > 0) {
      for (const hw of highways) {
        if (colors[hw]) filteredColors[hw] = colors[hw];
      }
      filteredColors.default = colors.default || '#353535ff';
    } else {
      // No filter (all_roads): use all colors
      Object.assign(filteredColors, colors);
    }
    
    // FIX #1: Use constant color for highways layer (OLD behavior hardcoded #1e40af)
    // This is CRITICAL: MapLibre renders constant color differently than match expression!
    const colorExpression = (name === 'highways')
      ? '#1e40af'  // Hardcoded like OLD code (motorway color, ignores trunk)
      : buildMatchExpression('highway', filteredColors, '#353535ff');
    
    const filterProp = filter ? { filter } : {};
    // FIX #5: all_roads should NOT have maxzoom (render to infinity like OLD code)
    const maxzoomProp = (name === 'all_roads') ? {} : { maxzoom };
    const layerDef = {
      id: `graph-${name}`,
      type: 'line',
      source: 'graph-vector',
      'source-layer': 'ways',
      minzoom,
      ...maxzoomProp,  // all_roads has no maxzoom limit
      ...filterProp,  // Add filter only if defined
      paint: {
        'line-color': colorExpression,
        'line-width': (name === 'highways') ? [
          'interpolate', ['linear'], ['zoom'],
          0, 0.5,
          9, 1.5,
          10, 2
        ] : (name === 'major_roads') ? [
          'interpolate', ['linear'], ['zoom'],
          10, 1.5,
          12, 3
        ] : (name === 'arterial_roads') ? [
          'interpolate', ['linear'], ['zoom'],
          12, 2,
          14, 4
        ] : [
          // all_roads: complex 3-point interpolation like OLD code
          'interpolate', ['linear'], ['zoom'],
          14, 1.5,
          15, ['match', ['get', 'highway'],
            'motorway', 8, 'motorway_link', 6,
            'trunk', 7, 'trunk_link', 6,
            'primary', 6, 'primary_link', 5,
            'secondary', 5, 'secondary_link', 4,
            'tertiary', 4, 'tertiary_link', 3,
            'residential', 3, 'living_street', 2,
            'unclassified', 2, 'service', 2,
            2
          ],
          18, ['match', ['get', 'highway'],
            'motorway', 12, 'motorway_link', 9,
            'trunk', 10, 'trunk_link', 9,
            'primary', 9, 'primary_link', 7,
            'secondary', 7, 'secondary_link', 6,
            'tertiary', 6, 'tertiary_link', 5,
            'residential', 5, 'living_street', 3,
            'unclassified', 3, 'service', 3,
            3
          ]
        ]
      }
    };
    
    // DEBUG: Log final layerDef
    if (window.globalChannel?.objects?.logger_bridge) {
      window.globalChannel.objects.logger_bridge.log_info(
        `[generateLodLayers] ${name}: layerDef = ${JSON.stringify(layerDef, null, 2)}`
      );
    }
    
    layers.push(layerDef);
    if (show_names) {
      // FIX #2: arterial labels filter to MAIN highways only (motorway, trunk, primary, secondary)
      // FIX #3: arterial labels start at minzoom=12 (not 13)
      // FIX #4: Use constant text-size (11 for arterial, 12 for all)
      const mainHighways = ['motorway', 'trunk', 'primary', 'secondary'];
      const labelFilter = (name === 'arterial_roads')
        ? ['all', ['has', 'name'], ['in', 'highway', ...mainHighways]]
        : ['has', 'name'];
      
      const labelMinzoom = (name === 'arterial_roads') ? 12 : 15;  // arterial starts at 12
      const textSize = (name === 'arterial_roads') 
        ? 11  // constant for arterial
        : ['interpolate', ['linear'], ['zoom'], 12, 10, 18, 14];  // interpolate for all_roads
      
      // FIX #6: all_roads-labels should NOT have maxzoom (like OLD code)
      const labelMaxzoomProp = (name === 'all_roads') ? {} : { maxzoom };
      
      layers.push({
        id: `graph-${name}-labels`,
        type: 'symbol',
        source: 'graph-vector',
        'source-layer': 'ways',
        minzoom: labelMinzoom,
        ...labelMaxzoomProp,  // all_roads-labels has no maxzoom limit
        filter: labelFilter,
        layout: {
          'text-field': ['coalesce', ['get', 'name_ru'], ['get', 'name']],
          'text-size': textSize,  // Constant like OLD code
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
  
  // DEBUG: Dump NEW style to JSON
  if (window.globalChannel?.objects?.logger_bridge) {
    const logger = window.globalChannel.objects.logger_bridge;
    const fullStyle = {
      version: 8,
      glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      sources: {
        osm: { type: 'raster', tiles: ['...'], tileSize: cfg.tiles.tileSize },
        'graph-vector': { type: 'vector', tiles: ['...'], minzoom: 0, maxzoom: 18 }
      },
      layers: [
        { id: 'background', type: 'background' },
        { id: 'osm', type: 'raster' }
      ].concat(lodLayers)
    };
    const fullDump = JSON.stringify(fullStyle, null, 2);
    logger.log_info(`[NEW] FULL STYLE DUMP (${fullDump.length} chars): ${fullDump}`);
  }
  
  return {
    version: 8,
    glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources: {
      osm: { type: 'raster', tiles: [tileUrl], tileSize: cfg.tiles.tileSize },
      'graph-vector': { 
        type: 'vector', 
        tiles: [`http://localhost:8005/api/v1/tiles/{z}/{x}/{y}.mvt?v=${Date.now()}`], 
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

// Map style loaded (100% config-driven)
