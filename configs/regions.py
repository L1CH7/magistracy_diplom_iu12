"""
Region configuration for bulk OSM data loading.

Defines which regions to preload into PostGIS cache.
Add bbox coordinates for regions you want to download.
If bbox is not defined, client will get empty response until data is loaded.
"""

# Format: 'region_name': [min_lon, min_lat, max_lon, max_lat]
# All coordinates in WGS84 (EPSG:4326)

REGIONS = {
    # Moscow Oblast (full region)
    'moscow_oblast': [35.0, 54.5, 40.0, 56.5],
    
    # Moscow city (smaller, for testing)
    'moscow_city': [37.35, 55.55, 37.85, 55.92],
    
    # Add more regions as needed:
    # 'saint_petersburg': [29.0, 59.0, 31.0, 60.5],
    # 'world': [-180.0, -90.0, 180.0, 90.0],  # Full planet (don't try this!)
}

# Default region for startup preloading (set to None to skip)
DEFAULT_REGION = None  # Changed from 'moscow_oblast' for manual loading

# Tile size for splitting large regions (degrees)
# ~0.1 deg = ~11km at Moscow latitude
TILE_SIZE_DEG = 0.1

# Overpass timeout per tile (seconds)
OVERPASS_TIMEOUT_SEC = 60

# Delay between tile fetches to avoid rate limiting (seconds)
TILE_FETCH_DELAY_SEC = 0.5
