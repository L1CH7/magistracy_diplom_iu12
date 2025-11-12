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

  setAssignedRoute(routeId, agentPosition = null) {
    /**
     * Set agent's assigned route (green from agent to end).
     * 
     * @param {number} routeId - Route ID
     * @param {Array} agentPosition - [lon, lat] of agent (clips geometry)
     */
    const oldRouteId = this._assignedRouteId;
    console.log(`[K-ROUTES] setAssignedRoute: ${routeId} at ${agentPosition}`);
    
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
    
    // Save new assigned route feature (with clipping if agent position provided)
    if (routeId !== null) {
      const src = this.map.getSource('k-routes');
      if (src) {
        const data = src._data || src._options?.data;
        if (data && data.features) {
          const feature = data.features.find(f => f.properties.route_id === routeId);
          if (feature) {
            let savedFeature = JSON.parse(JSON.stringify(feature));
            
            // Clip geometry from EXACT agent position to end
            if (agentPosition && feature.geometry.type === 'LineString') {
              const coords = feature.geometry.coordinates;
              
              // Find closest segment and project agent onto it
              let closestIdx = 0;
              let minDist = Infinity;
              let bestT = 0;  // Projection parameter [0, 1]
              
              for (let i = 0; i < coords.length - 1; i++) {
                const a = coords[i];
                const b = coords[i + 1];
                
                // Project agent onto segment
                const dx = b[0] - a[0];
                const dy = b[1] - a[1];
                const lenSq = dx * dx + dy * dy;
                
                let t = 0;
                if (lenSq > 1e-10) {
                  const apx = agentPosition[0] - a[0];
                  const apy = agentPosition[1] - a[1];
                  t = Math.max(0, Math.min(1, (apx * dx + apy * dy) / lenSq));
                }
                
                // Closest point on segment
                const projX = a[0] + t * dx;
                const projY = a[1] + t * dy;
                
                // Distance to projected point
                const distX = agentPosition[0] - projX;
                const distY = agentPosition[1] - projY;
                const dist = Math.sqrt(distX * distX + distY * distY);
                
                if (dist < minDist) {
                  minDist = dist;
                  closestIdx = i;
                  bestT = t;
                }
              }
              
              // Build clipped geometry: start with projected agent position
              const a = coords[closestIdx];
              const b = coords[closestIdx + 1];
              const projectedPoint = [
                a[0] + bestT * (b[0] - a[0]),
                a[1] + bestT * (b[1] - a[1])
              ];
              
              // Clipped coords: projected point + remaining segments
              const clippedCoords = [projectedPoint, ...coords.slice(closestIdx + 1)];
              savedFeature.geometry.coordinates = clippedCoords;
              
              console.log(`[K-ROUTES] Clipped route from agent at segment ${closestIdx} (t=${bestT.toFixed(3)})`);
              
              // UPDATE SOURCE with clipped feature
              const otherFeatures = data.features.filter(
                f => f.properties.route_id !== routeId
              );
              src.setData({
                type: 'FeatureCollection',
                features: [...otherFeatures, savedFeature]
              });
              console.log(`[K-ROUTES] Updated source with clipped feature`);
            }
            
            this._assignedRouteFeature = savedFeature;
            console.log(`[K-ROUTES] Saved assigned route feature ${routeId}`);
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

  _pointToSegmentDistance(point, segStart, segEnd) {
    /**
     * Calculate distance from point to line segment.
     * 
     * @param {Array} point - [lon, lat]
     * @param {Array} segStart - [lon, lat]
     * @param {Array} segEnd - [lon, lat]
     * @returns {number} Distance in degrees (approximate)
     */
    const px = point[0], py = point[1];
    const ax = segStart[0], ay = segStart[1];
    const bx = segEnd[0], by = segEnd[1];
    
    // Vector AB
    const dx = bx - ax;
    const dy = by - ay;
    
    // Vector AP
    const apx = px - ax;
    const apy = py - ay;
    
    // Squared length of AB
    const lenSq = dx * dx + dy * dy;
    
    if (lenSq < 1e-10) {
      // Segment is a point
      return Math.sqrt(apx * apx + apy * apy);
    }
    
    // Projection of AP onto AB
    let t = (apx * dx + apy * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));  // Clamp to [0, 1]
    
    // Closest point on segment
    const closestX = ax + t * dx;
    const closestY = ay + t * dy;
    
    // Distance to closest point
    const distX = px - closestX;
    const distY = py - closestY;
    
    return Math.sqrt(distX * distX + distY * distY);
  }

  // Deprecated/stub methods for compatibility
  setPickMode(mode) {
    console.log('setPickMode called with:', mode, '(deprecated; use context menu)');
  }
}
