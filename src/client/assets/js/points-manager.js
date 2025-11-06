/**
 * Points management - handling picked points (from/via/to) on the map.
 */

import { createMarkerElement, getMarkerType, getMarkerColor } from './markers.js';

export class PointsManager {
  constructor(map) {
    this.map = map;
    this.allPoints = [];  // Array of {lon, lat, color, display_color, display_type}
    this.allMarkers = [];
    this.pendingOperations = [];
    this.mapLoaded = false;
  }

  setMapLoaded(loaded) {
    this.mapLoaded = loaded;
    if (loaded) {
      this._processPendingOperations();
    }
  }

  _processPendingOperations() {
    const ops = this.pendingOperations.slice();
    this.pendingOperations = [];
    ops.forEach(op => {
      switch (op.type) {
        case 'setStart':
          this.setStart(op.lngLat);
          break;
        case 'setEnd':
          this.setEnd(op.lngLat);
          break;
        case 'addMarker':
          this.addMarker(op.lngLat, op.color);
          break;
      }
    });
  }

  _addMarkerToMap(lngLat, type, color) {
    if (!this.map || !this.mapLoaded) return null;

    const el = createMarkerElement(type, color);
    const marker = new maplibregl.Marker({
      element: el,
      pitchAlignment: 'map',
      rotationAlignment: 'map',
    });

    const lng = lngLat.lon !== undefined ? lngLat.lon : lngLat.lng;
    const lat = lngLat.lat;
    marker.setLngLat([lng, lat]).addTo(this.map);
    this.allMarkers.push(marker);
    return marker;
  }

  setStart(lngLat) {
    console.log('setStart called:', lngLat, 'mapLoaded:', this.mapLoaded);
    if (!this.mapLoaded) {
      this.pendingOperations.push({ type: 'setStart', lngLat });
      console.log('Map not loaded, queued setStart');
      return;
    }

    const lon = lngLat.lng !== undefined ? lngLat.lng : lngLat.lon;
    const point = {
      lon: lon,
      lat: lngLat.lat,
      color: lngLat.color || '#8b5cf6',
    };

    if (this.allPoints.length === 0) {
      this.allPoints.push(point);
    } else {
      this.allPoints[0] = point;
    }

    this._redrawAllMarkers();
    console.log('Start point set, allPoints:', this.allPoints.length);
  }

  setEnd(lngLat) {
    console.log('setEnd called:', lngLat, 'mapLoaded:', this.mapLoaded);
    if (!this.mapLoaded) {
      this.pendingOperations.push({ type: 'setEnd', lngLat });
      console.log('Map not loaded, queued setEnd');
      return;
    }

    const lon = lngLat.lng !== undefined ? lngLat.lng : lngLat.lon;
    const point = {
      lon: lon,
      lat: lngLat.lat,
      color: lngLat.color || '#8b5cf6',
    };

    if (this.allPoints.length === 0) {
      this.allPoints.push(point);
    } else if (this.allPoints.length === 1) {
      this.allPoints.push(point);
    } else {
      this.allPoints[this.allPoints.length - 1] = point;
    }

    this._redrawAllMarkers();
    console.log('End point set, allPoints:', this.allPoints.length);
  }

  addMarker(lngLat, color) {
    if (!this.mapLoaded) {
      this.pendingOperations.push({ type: 'addMarker', lngLat, color });
      return;
    }

    const lon = lngLat.lon !== undefined ? lngLat.lon : lngLat.lng;
    const point = { lon: lon, lat: lngLat.lat, color: color || '#8b5cf6' };

    // Add via point (insert before last if we have from+to, else just append)
    if (this.allPoints.length >= 2) {
      this.allPoints.splice(this.allPoints.length - 1, 0, point);
    } else {
      this.allPoints.push(point);
    }

    this._redrawAllMarkers();
    console.log('Via point added, allPoints:', this.allPoints.length);
  }

  _redrawAllMarkers() {
    // Clear all existing markers
    this.allMarkers.forEach(m => m.remove());
    this.allMarkers = [];

    // Add marker for each point
    this.allPoints.forEach((point, idx) => {
      const type = getMarkerType(idx, this.allPoints.length, point);
      const color = getMarkerColor(type, point);
      const marker = this._addMarkerToMap(point, type, color);
      if (marker) {
        this.allMarkers.push(marker);
      }
    });

    console.log('Markers redrawn:', this.allPoints.length);
    this._notifyPointsChanged();
  }

  _notifyPointsChanged() {
    if (window.pointsChangedCallback) {
      window.pointsChangedCallback();
    }
  }

  addVia(lngLat) {
    return this.addMarker(lngLat, '#f59e0b');
  }

  clearVia() {
    if (!this.mapLoaded) return;
    this.allMarkers.forEach(m => m.remove());
    this.allMarkers = [];
  }

  clearAllMarkers() {
    this.allMarkers.forEach(m => m.remove());
    this.allMarkers = [];
    this.allPoints = [];
  }

  getPickedPoints() {
    const start = this.allPoints.length > 0 ? this.allPoints[0] : null;
    const end = this.allPoints.length > 1 ? this.allPoints[this.allPoints.length - 1] : null;
    const via = this.allPoints.length > 2 ? this.allPoints.slice(1, -1) : [];
    return { start, end, via };
  }

  setAllPoints(points) {
    // Replace entire allPoints array and redraw markers
    this.allPoints = points.slice();
    console.log('setAllPoints called with:', this.allPoints.length, 'points');
    console.log('Display colors:', this.allPoints.map(p => p.display_color || 'N/A'));
    console.log('Display types:', this.allPoints.map(p => p.display_type || 'N/A'));
    this._redrawAllMarkers();
  }

  clearPicked() {
    this.clearAllMarkers();
  }
}
