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
    this._selectedRouteId = null;  // User-selected route (blue)
    this._assignedRouteId = null;  // Agent's assigned route (green)
    this._assignedRouteFeature = null;  // Saved assigned route feature
    this._currentRouteIds = new Set();  // Track route IDs from last displayRoutes()
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
  
  removeAgent() {
    this.agentAnimator.removeAgent();
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

  // K-routes API - display multiple alternative routes
  displayRoutes(geojson) {
    /**
     * Display K alternative routes (shared_ptr model).
     * Logic:
     * - New routes replace old routes completely
     * - If assigned route is IN new routes: it stays (has references)
     * - If assigned route is NOT in new routes: keep it only if agent owns it
     * - Auto-select first route (blue)
     */
    const src = this.map.getSource('k-routes');
    if (!src) {
      console.error('k-routes source not found');
      return;
    }
    
    const newRoutes = [...geojson.features];
    const newRouteIds = new Set(newRoutes.map(f => f.properties.route_id));
    
    // Track current route IDs for reference counting
    this._currentRouteIds = newRouteIds;
    
    // Check if assigned route still has references
    let finalFeatures = [...newRoutes];
    if (this._assignedRouteId !== null) {
      if (newRouteIds.has(this._assignedRouteId)) {
        // Assigned route is in new routes - it has reference, keep it
        console.log(`[K-ROUTES] Assigned route ${this._assignedRouteId} found in new routes`);
      } else if (this._assignedRouteFeature) {
        // Assigned route NOT in new routes - but agent owns it, add it back
        finalFeatures.push(this._assignedRouteFeature);
        console.log(`[K-ROUTES] Assigned route ${this._assignedRouteId} not in new routes, keeping for agent`);
      }
    }
    
    // Reverse for proper rendering order
    const reversedFeatures = [...finalFeatures].reverse();
    src.setData({
      type: 'FeatureCollection',
      features: reversedFeatures
    });
    
    console.log(`[K-ROUTES] Displayed ${newRoutes.length} new routes, ${finalFeatures.length} total`);
    
    // Auto-select first route (blue)
    if (newRoutes.length > 0) {
      const firstRouteId = newRoutes[0].properties.route_id;
      this._selectedRouteId = firstRouteId;
      console.log(`[K-ROUTES] Auto-selected first route: ${firstRouteId}`);
    } else {
      this._selectedRouteId = null;
    }
    
    this._updateKRouteFilters();
  }

  highlightRoute(routeId) {
    /**
     * DEPRECATED: Use setSelectedRoute() instead.
     * Kept for backward compatibility.
     */
    this.setSelectedRoute(routeId);
  }

  setSelectedRoute(routeId) {
    /**
     * Set user-selected route (blue).
     * @param {number|null} routeId - The route_id to select (null to clear)
     */
    console.log(`[K-ROUTES] setSelectedRoute: ${routeId} (previous: ${this._selectedRouteId})`);
    this._selectedRouteId = routeId;
    
    // Debug: Check if route exists in source
    const src = this.map.getSource('k-routes');
    if (src && routeId !== null) {
      const data = src._data || src._options?.data;
      if (data && data.features) {
        const exists = data.features.some(f => f.properties.route_id === routeId);
        console.log(`[K-ROUTES] Route ${routeId} exists in source: ${exists}, total features: ${data.features.length}`);
        if (!exists) {
          console.error(`[K-ROUTES] Route ${routeId} NOT FOUND in features! Available:`, data.features.map(f => f.properties.route_id));
        }
      }
    }
    
    this._updateKRouteFilters();
  }

  setAssignedRoute(routeId) {
    /**
     * Set agent's assigned route (green).
     * When route changes, old route loses its reference and should be removed.
     */
    const oldRouteId = this._assignedRouteId;
    console.log(`[K-ROUTES] setAssignedRoute: ${routeId} (previous: ${oldRouteId})`);
    
    // If route changed, need to update source to remove old route
    if (routeId !== oldRouteId && oldRouteId !== null) {
      const src = this.map.getSource('k-routes');
      if (src) {
        const data = src._data || src._options?.data;
        if (data && data.features) {
          // Remove old assigned route if it's not in current routes list
          const newFeatures = data.features.filter(f => {
            const fid = f.properties.route_id;
            // Keep if: not old route, OR is in routes list (has other references)
            return fid !== oldRouteId || this._isInCurrentRoutes(fid);
          });
          
          if (newFeatures.length < data.features.length) {
            src.setData({
              type: 'FeatureCollection',
              features: newFeatures
            });
            console.log(`[K-ROUTES] Removed old assigned route ${oldRouteId} (no references left)`);
          }
        }
      }
      this._assignedRouteFeature = null;
    }
    
    this._assignedRouteId = routeId;
    
    // Save new assigned route feature
    if (routeId !== null) {
      const src = this.map.getSource('k-routes');
      if (src) {
        const data = src._data || src._options?.data;
        if (data && data.features) {
          const feature = data.features.find(f => f.properties.route_id === routeId);
          if (feature) {
            this._assignedRouteFeature = JSON.parse(JSON.stringify(feature));
            console.log(`[K-ROUTES] Saved new assigned route feature ${routeId}`);
          } else {
            console.warn(`[K-ROUTES] Route ${routeId} not found in current features!`);
          }
        }
      }
    } else {
      this._assignedRouteFeature = null;
    }
    
    this._updateKRouteFilters();
  }
  
  _isInCurrentRoutes(routeId) {
    /**
     * Check if route is in current displayRoutes() result.
     */
    return this._currentRouteIds.has(routeId);
  }

  _updateKRouteFilters() {
    /**
     * Update MapLibre layer filters for 3-tier route visualization:
     * - Gray: all routes (inactive)
     * - Blue: user-selected route (selected)
     * - Green: agent's assigned route (assigned) - highest priority
     */
    const assigned = this._assignedRouteId;
    const selected = this._selectedRouteId;
    
    console.log(`[K-ROUTES] Updating filters: assigned=${assigned}, selected=${selected}`);

    // Assigned route (green, highest priority)
    if (assigned !== null) {
      this.map.setFilter('k-routes-assigned', ['==', ['get', 'route_id'], assigned]);
      this.map.setFilter('k-routes-assigned-casing', ['==', ['get', 'route_id'], assigned]);
    } else {
      this.map.setFilter('k-routes-assigned', ['==', ['get', 'route_id'], -1]);
      this.map.setFilter('k-routes-assigned-casing', ['==', ['get', 'route_id'], -1]);
    }

    // Selected route (blue), but not if it's assigned
    if (selected !== null && selected !== assigned) {
      this.map.setFilter('k-routes-selected', ['==', ['get', 'route_id'], selected]);
      this.map.setFilter('k-routes-selected-casing', ['==', ['get', 'route_id'], selected]);
    } else {
      this.map.setFilter('k-routes-selected', ['==', ['get', 'route_id'], -1]);
      this.map.setFilter('k-routes-selected-casing', ['==', ['get', 'route_id'], -1]);
    }

    // Inactive routes (gray) - all except assigned and selected
    const excludedIds = [assigned, selected].filter(id => id !== null);
    if (excludedIds.length === 0) {
      // No exclusions - show all
      this.map.setFilter('k-routes-inactive', ['!=', ['get', 'route_id'], -1]);
      this.map.setFilter('k-routes-inactive-casing', ['!=', ['get', 'route_id'], -1]);
    } else if (excludedIds.length === 1) {
      // Exclude one
      this.map.setFilter('k-routes-inactive', ['!=', ['get', 'route_id'], excludedIds[0]]);
      this.map.setFilter('k-routes-inactive-casing', ['!=', ['get', 'route_id'], excludedIds[0]]);
    } else {
      // Exclude both (assigned and selected are different)
      this.map.setFilter('k-routes-inactive', [
        'all',
        ['!=', ['get', 'route_id'], excludedIds[0]],
        ['!=', ['get', 'route_id'], excludedIds[1]]
      ]);
      this.map.setFilter('k-routes-inactive-casing', [
        'all',
        ['!=', ['get', 'route_id'], excludedIds[0]],
        ['!=', ['get', 'route_id'], excludedIds[1]]
      ]);
    }
  }

  clearKRoutes() {
    /**
     * Clear all K routes from the map.
     */
    const src = this.map.getSource('k-routes');
    if (src) {
      src.setData({ type: 'FeatureCollection', features: [] });
      this._selectedRouteId = null;
      this._assignedRouteId = null;
      console.log('Cleared K routes');
    }
  }

  // Deprecated/stub methods for compatibility
  setPickMode(mode) {
    console.log('setPickMode called with:', mode, '(deprecated; use context menu)');
  }
}
