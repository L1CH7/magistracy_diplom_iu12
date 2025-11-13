/**
 * Dynamic tile-based road graph loader.
 * 
 * Strategy:
 * 1. Calculate visible tiles based on map viewport
 * 2. Request only missing tiles from server
 * 3. Accumulate features as tiles load
 * 4. Update map incrementally
 */

export class TileLoader {
  constructor(map, apiBaseUrl) {
    this.map = map;
    this.apiBaseUrl = apiBaseUrl;
    this.tileSize = 0.05; // degrees (~5.5km)
    this.loadedTiles = new Set(); // tile_keys already loaded
    this.allFeatures = []; // accumulated GeoJSON features
    this.loading = false;
    
    console.log('[TILE LOADER] Initialized', {
      tileSize: this.tileSize,
      apiUrl: apiBaseUrl
    });
  }
  
  /**
   * Calculate tile keys for current viewport.
   * 
   * @param {number} bufferFactor - Buffer around viewport (default 0.5)
   * @returns {Array<string>} Array of tile_keys
   */
  getViewportTiles(bufferFactor = 0.5) {
    const bounds = this.map.getBounds();
    const west = bounds.getWest();
    const east = bounds.getEast();
    const south = bounds.getSouth();
    const north = bounds.getNorth();
    
    const lonRange = east - west;
    const latRange = north - south;
    
    // Add buffer
    const minLon = west - lonRange * bufferFactor;
    const maxLon = east + lonRange * bufferFactor;
    const minLat = south - latRange * bufferFactor;
    const maxLat = north + latRange * bufferFactor;
    
    // Calculate tile grid
    const tiles = [];
    let lat = Math.floor(minLat / this.tileSize) * this.tileSize;
    
    while (lat < maxLat) {
      let lon = Math.floor(minLon / this.tileSize) * this.tileSize;
      
      while (lon < maxLon) {
        const tileKey = `${lat.toFixed(2)}_${lon.toFixed(2)}`;
        tiles.push(tileKey);
        lon += this.tileSize;
      }
      
      lat += this.tileSize;
    }
    
    return tiles;
  }
  
  /**
   * Load tiles for current viewport.
   * 
   * @returns {Promise<void>}
   */
  async loadViewportTiles() {
    if (this.loading) {
      console.log('[TILE LOADER] Already loading, skipping');
      return;
    }
    
    this.loading = true;
    
    try {
      const viewportTiles = this.getViewportTiles(0.5);
      const missingTiles = viewportTiles.filter(
        key => !this.loadedTiles.has(key)
      );
      
      if (missingTiles.length === 0) {
        console.log('[TILE LOADER] All tiles cached');
        this.loading = false;
        return;
      }
      
      console.log(
        `[TILE LOADER] Loading ${missingTiles.length} tiles ` +
        `(${this.loadedTiles.size} already cached)`
      );
      
      // Load tiles in parallel (max 5 concurrent)
      const batchSize = 5;
      for (let i = 0; i < missingTiles.length; i += batchSize) {
        const batch = missingTiles.slice(i, i + batchSize);
        await Promise.all(batch.map(key => this.loadTile(key)));
      }
      
      console.log(
        `[TILE LOADER] Complete: ${this.loadedTiles.size} tiles, ` +
        `${this.allFeatures.length} total features`
      );
      
    } finally {
      this.loading = false;
    }
  }
  
  /**
   * Load single tile from server.
   * 
   * @param {string} tileKey - Tile identifier "lat_lon"
   * @returns {Promise<void>}
   */
  async loadTile(tileKey) {
    try {
      const url = `${this.apiBaseUrl}/osm/fetch_tile/${tileKey}`;
      const response = await fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`
        );
      }
      
      const data = await response.json();
      
      if (data.type === 'success' && data.geojson) {
        const features = data.geojson.features || [];
        
        // Add features to accumulator
        this.allFeatures.push(...features);
        this.loadedTiles.add(tileKey);
        
        // Update map source incrementally
        this.updateMapSource();
        
        console.log(
          `[TILE LOADER] ${tileKey}: +${features.length} roads ` +
          `(total: ${this.allFeatures.length})`
        );
      }
      
    } catch (error) {
      console.error(`[TILE LOADER] Failed to load ${tileKey}:`, error);
    }
  }
  
  /**
   * Update map source with all accumulated features.
   */
  updateMapSource() {
    const src = this.map.getSource('graph');
    if (src) {
      src.setData({
        type: 'FeatureCollection',
        features: this.allFeatures
      });
    }
  }
  
  /**
   * Clear all loaded tiles and features.
   */
  clear() {
    this.loadedTiles.clear();
    this.allFeatures = [];
    this.updateMapSource();
    console.log('[TILE LOADER] Cleared');
  }
  
  /**
   * Get loading statistics.
   * 
   * @returns {Object} Stats
   */
  getStats() {
    return {
      tilesLoaded: this.loadedTiles.size,
      featuresLoaded: this.allFeatures.length,
      loading: this.loading
    };
  }
}
