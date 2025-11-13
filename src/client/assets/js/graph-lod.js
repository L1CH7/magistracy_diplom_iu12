/**
 * Graph optimization utilities - LOD (Level of Detail) rendering.
 * 
 * Strategy: Filter roads by highway type based on zoom level.
 * - Zoom 0-10: Only motorways
 * - Zoom 11-12: + primary roads
 * - Zoom 13-14: + secondary/tertiary
 * - Zoom 15+: All roads
 */

export const GRAPH_LOD = {
  // Zoom thresholds (more aggressive - show more roads earlier)
  ZOOM_MOTORWAY: 0,      // Show motorways from zoom 0
  ZOOM_PRIMARY: 10,      // Add primary from zoom 10
  ZOOM_SECONDARY: 11,    // Add secondary/tertiary from zoom 11
  ZOOM_ALL: 12,          // Show all roads from zoom 12
  
  // Highway types by importance
  MOTORWAY_TYPES: new Set(['motorway', 'motorway_link']),
  PRIMARY_TYPES: new Set(['trunk', 'trunk_link', 'primary', 'primary_link']),
  SECONDARY_TYPES: new Set([
    'secondary', 'secondary_link',
    'tertiary', 'tertiary_link'
  ]),
  
  /**
   * Filter GeoJSON features by zoom level (LOD).
   * 
   * @param {Object} geojson - Full GeoJSON FeatureCollection
   * @param {number} zoom - Current map zoom level
   * @returns {Object} Filtered GeoJSON
   */
  filterByZoom(geojson, zoom) {
    if (!geojson || !geojson.features) {
      return { type: 'FeatureCollection', features: [] };
    }
    
    const features = geojson.features;
    
    // Zoom >= 15: Show everything
    if (zoom >= this.ZOOM_ALL) {
      return geojson;
    }
    
    // Filter by road type
    const filtered = features.filter(f => {
      const highway = f.properties?.highway;
      if (!highway) return false;
      
      // Always show motorways
      if (this.MOTORWAY_TYPES.has(highway)) return true;
      
      // Zoom 11+: Add primary roads
      if (zoom >= this.ZOOM_PRIMARY && this.PRIMARY_TYPES.has(highway)) {
        return true;
      }
      
      // Zoom 13+: Add secondary/tertiary
      if (zoom >= this.ZOOM_SECONDARY && this.SECONDARY_TYPES.has(highway)) {
        return true;
      }
      
      return false;
    });
    
    console.log(
      `[GRAPH LOD] Zoom ${zoom.toFixed(1)}: ` +
      `${filtered.length}/${features.length} roads (` +
      `${((filtered.length / features.length) * 100).toFixed(1)}%)`
    );
    
    return {
      type: 'FeatureCollection',
      features: filtered
    };
  },
  
  /**
   * Get statistics about feature types.
   * 
   * @param {Object} geojson - GeoJSON FeatureCollection
   * @returns {Object} Statistics by highway type
   */
  getStats(geojson) {
    if (!geojson || !geojson.features) {
      return {};
    }
    
    const stats = {};
    geojson.features.forEach(f => {
      const highway = f.properties?.highway || 'unknown';
      stats[highway] = (stats[highway] || 0) + 1;
    });
    
    return stats;
  }
};

