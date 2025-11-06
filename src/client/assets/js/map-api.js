/**
 * Map API - public interface for PyQt interaction.
 */

import { MAP_CONFIG } from './map-config.js';

export class MapAPI {
  constructor(map, pointsManager, agentAnimator) {
    this.map = map;
    this.pointsManager = pointsManager;
    this.agentAnimator = agentAnimator;
    this._skipNextZoomUpdate = false;
  }

  setGraphGeoJSON(geojson) {
    const src = this.map.getSource('graph');
    if (src) {
      src.setData(geojson);
    }
  }

  fitToGraph() {
    const src = this.map.getSource('graph');
    if (!src) return;

    const data = src._data || src._options?.data;
    if (!data || !data.features || data.features.length === 0) return;

    const coords = data.features.flatMap(f => f.geometry.coordinates);
    if (!coords || coords.length === 0) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    coords.forEach(([x, y]) => {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    });

    if (isFinite(minX)) {
      this.map.fitBounds(
        [[minX, minY], [maxX, maxY]],
        {
          padding: MAP_CONFIG.animation.fitBoundsPadding,
          duration: MAP_CONFIG.animation.fitBoundsDuration,
          maxZoom: MAP_CONFIG.animation.fitBoundsMaxZoom,
        }
      );
    }
  }

  setRoutes(routes) {
    // routes: [{ id, coords: [[lon,lat], ...], color?: '#rrggbb' }]
    const features = routes.map(r => ({
      type: 'Feature',
      properties: {
        id: r.id ?? '',
        color: r.color ?? MAP_CONFIG.layers.routes.defaultColor,
      },
      geometry: { type: 'LineString', coordinates: r.coords },
    }));

    const src = this.map.getSource('routes');
    if (src) {
      src.setData({ type: 'FeatureCollection', features });
    }
  }

  updateAgent(pos) {
    this.agentAnimator.updateAgent(pos);
  }

  fitToRoutes() {
    const src = this.map.getSource('routes');
    if (!src) return;

    const data = src._data || src._options?.data;
    if (!data || !data.features || data.features.length === 0) return;

    const coords = data.features.flatMap(f => f.geometry.coordinates);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    coords.forEach(([x, y]) => {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    });

    if (isFinite(minX)) {
      this.map.fitBounds(
        [[minX, minY], [maxX, maxY]],
        { padding: 60, duration: 600, maxZoom: 16 }
      );
    }
  }

  // Points API - delegated to PointsManager
  addMarker(lngLat, color = '#8b5cf6') {
    return this.pointsManager.addMarker(lngLat, color);
  }

  getPickedPoints() {
    return this.pointsManager.getPickedPoints();
  }

  setAllPoints(points) {
    this.pointsManager.setAllPoints(points);
  }

  clearPicked() {
    this.pointsManager.clearPicked();
  }

  setStart(lngLat) {
    this.pointsManager.setStart(lngLat);
  }

  setEnd(lngLat) {
    this.pointsManager.setEnd(lngLat);
  }

  addVia(lngLat) {
    this.pointsManager.addVia(lngLat);
  }

  clearVia() {
    this.pointsManager.clearVia();
  }

  clearAllMarkers() {
    this.pointsManager.clearAllMarkers();
  }

  // Zoom API
  zoomIn() {
    if (this.map) {
      this.map.zoomIn({ duration: MAP_CONFIG.animation.zoomDuration });
    }
  }

  zoomOut() {
    if (this.map) {
      this.map.zoomOut({ duration: MAP_CONFIG.animation.zoomDuration });
    }
  }

  setZoom(level) {
    if (this.map) {
      this._skipNextZoomUpdate = true;
      this.map.jumpTo({ zoom: level });
    }
  }

  getZoom() {
    return this.map ? this.map.getZoom() : null;
  }

  shouldSkipZoomUpdate() {
    const skip = this._skipNextZoomUpdate;
    this._skipNextZoomUpdate = false;
    return skip;
  }

  // Deprecated/stub methods for compatibility
  setPickMode(mode) {
    console.log('setPickMode called with:', mode, '(deprecated; use context menu)');
  }
}
