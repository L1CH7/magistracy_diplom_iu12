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
  constructor(map, apiBaseUrl, maxBounds) {
    this.map = map;
    this.apiBaseUrl = apiBaseUrl;
    this.tileSize = 0.05; // degrees (~5.5km)
    this.loadedTiles = new Set(); // tile_keys already loaded
    this.allFeatures = []; // accumulated GeoJSON features
    this.loading = false;
    
    // Max bounds - only download tiles within this area
    this.maxBounds = maxBounds || {
      west: 37.50,
      south: 55.70,
      east: 37.70,
      north: 55.80
    };
    
    console.log('[TILE LOADER] Initialized', {
      tileSize: this.tileSize,
      apiUrl: apiBaseUrl,
      maxBounds: this.maxBounds
    });
  }
  
  /**
   * Calculate tile keys for current viewport.
   * 
   * ONLY returns tiles within maxBounds (moscow_medium by default).
   * Viewport is STRICTLY intersected with maxBounds (no buffer outside).
   * 
   * @returns {Array<string>} Array of tile_keys "lat_lon"
   */
  getViewportTiles() {
    const bounds = this.map.getBounds();
    const origWest = bounds.getWest();
    const origEast = bounds.getEast();
    const origSouth = bounds.getSouth();
    const origNorth = bounds.getNorth();
    
    let west = origWest;
    let east = origEast;
    let south = origSouth;
    let north = origNorth;
    
    // Log original viewport before intersection
    console.log(`[TILE LOADER] Original viewport: [${origWest.toFixed(4)}, ${origSouth.toFixed(4)}, ${origEast.toFixed(4)}, ${origNorth.toFixed(4)}] (size: ${(origEast-origWest).toFixed(4)}° × ${(origNorth-origSouth).toFixed(4)}°)`);
    
    // STRICT intersection with maxBounds - no buffer outside
    west = Math.max(west, this.maxBounds.west);
    east = Math.min(east, this.maxBounds.east);
    south = Math.max(south, this.maxBounds.south);
    north = Math.min(north, this.maxBounds.north);
    
    // If viewport doesn't intersect maxBounds at all, return empty
    if (west >= east || south >= north) {
      console.log(`[TILE LOADER] Viewport doesn't intersect maxBounds, no tiles`);
      return [];
    }
    
    console.log(`[TILE LOADER] Intersected with maxBounds: [${west.toFixed(4)}, ${south.toFixed(4)}, ${east.toFixed(4)}, ${north.toFixed(4)}]`);
    
    // Calculate tile grid ONLY within intersection
    // Tile at (lon, lat) covers [lon, lon+tileSize) x [lat, lat+tileSize)
    // So we need: lon >= west AND lon+tileSize <= east (to stay within bounds)
    const tiles = [];
    const startLat = Math.ceil(south / this.tileSize) * this.tileSize;
    const startLon = Math.ceil(west / this.tileSize) * this.tileSize;
    
    let lat = startLat;
    while (lat < north && lat + this.tileSize <= this.maxBounds.north) {
      let lon = startLon;
      
      while (lon < east && lon + this.tileSize <= this.maxBounds.east) {
        // Add tile (guaranteed to be fully within maxBounds)
        const tileKey = `${lat.toFixed(2)}_${lon.toFixed(2)}`;
        tiles.push(tileKey);
        lon += this.tileSize;
      }
      
      lat += this.tileSize;
    }
    
    console.log(`[TILE LOADER] Calculated ${tiles.length} tiles for viewport (bounds: [${west.toFixed(2)}, ${south.toFixed(2)}, ${east.toFixed(2)}, ${north.toFixed(2)}])`);
    return tiles;
  }
  
  /**
   * Load tiles for current viewport.
   * 
   * @returns {Promise<void>}
   */
  async loadViewportTiles() {
    console.log('[TILE LOADER] loadViewportTiles() called');
    
    if (this.loading) {
      console.log('[TILE LOADER] Already loading, skipping');
      return;
    }
    
    this.loading = true;
    
    try {
      // Get tiles for current viewport (strictly within maxBounds)
      const viewportTiles = this.getViewportTiles();
      
      const missingTiles = viewportTiles.filter(
        key => !this.loadedTiles.has(key)
      );
      
      if (missingTiles.length === 0) {
        console.log('[TILE LOADER] All viewport tiles already loaded');
        this.loading = false;
        return;
      }
      
      console.log(
        `[TILE LOADER] Loading ${missingTiles.length} missing tiles ` +
        `(${this.loadedTiles.size} already loaded)`
      );
      
      // Load tiles sequentially for better progress visibility
      for (let i = 0; i < missingTiles.length; i++) {
        const tileKey = missingTiles[i];
        console.log(`[TILE LOADER] Loading tile ${i+1}/${missingTiles.length}: ${tileKey}`);
        await this.loadTile(tileKey);
      }
      
      console.log(
        `[TILE LOADER] Complete: ${this.loadedTiles.size} tiles total loaded`
      );
      
    } catch (error) {
      console.error('[TILE LOADER] Error:', error);
    } finally {
      this.loading = false;
    }
  }
  
  /**
   * Load single OSM tile from Data Processor.
   * 
   * @param {string} tileKey - Tile identifier "lat_lon"
   * @returns {Promise<void>}
   */
  async loadTile(tileKey) {
    try {
      // Parse tileKey (format: "55.70_37.50")
      const [latStr, lonStr] = tileKey.split('_');
      const lat = parseFloat(latStr);
      const lon = parseFloat(lonStr);
      
      // Call Data Processor /tiles/download endpoint
      const bbox_size = 0.2;  // Default tile size
      const url = `http://localhost:8005/api/v1/tiles/download?lon=${lon}&lat=${lat}&bbox_size=${bbox_size}`;
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (!response.ok) {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`
        );
      }
      
      const data = await response.json();
      
      // Mark as loaded and trigger MVT refresh
      if (data.status === 'started') {
        this.loadedTiles.add(tileKey);
        
        console.log(
          `[TILE LOADER] ${tileKey}: download started ` +
          `(tile_key: ${data.tile_key})`
        );
        
        // Reload MVT layer to show new data after download completes
        const vectorSource = this.map.getSource('graph-vector');
        if (vectorSource) {
          // Wait a bit for download to complete, then repaint
          setTimeout(() => {
            this.map.triggerRepaint();
          }, 5000);  // 5 seconds should be enough for most tiles
        }
      }
      
    } catch (error) {
      console.error(`[TILE LOADER] Failed to load ${tileKey}:`, error);
    }
  }
  
  /**
   * Update MVT vector source (reload tiles).
   */
  updateMapSource() {
    // MVT source reloads automatically, just trigger repaint
    const vectorSource = this.map.getSource('graph-vector');
    if (vectorSource) {
      this.map.triggerRepaint();
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
