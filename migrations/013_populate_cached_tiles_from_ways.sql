-- Migration: Populate cached_tiles from existing ways
-- Purpose: Fill cached_tiles table with tile info for all tiles that have ways in DB
-- This enables in-memory cache preloading for existing data

-- Insert tiles from ways into cached_tiles
INSERT INTO osm.cached_tiles (
    tile_key,
    min_lon,
    min_lat,
    max_lon,
    max_lat,
    bbox,
    total_ways,
    download_status,
    downloaded_at,
    created_at,
    accessed_at
)
SELECT DISTINCT
    -- Generate tile_key "37.50_55.75"
    ROUND(CAST(tile_lon AS NUMERIC), 2)::TEXT || '_' || ROUND(CAST(tile_lat AS NUMERIC), 2)::TEXT AS tile_key,
    
    -- Tile bounds (TILE_SIZE = 0.05 degrees for legacy tiles)
    tile_lon AS min_lon,
    tile_lat AS min_lat,
    tile_lon + 0.05 AS max_lon,
    tile_lat + 0.05 AS max_lat,
    
    -- Bbox polygon
    ST_MakeEnvelope(tile_lon, tile_lat, tile_lon + 0.05, tile_lat + 0.05, 4326) AS bbox,
    
    -- Count ways in this tile
    (
        SELECT COUNT(*)
        FROM osm.ways w2
        WHERE w2.geom && ST_MakeEnvelope(tile_lon, tile_lat, tile_lon + 0.05, tile_lat + 0.05, 4326)
    ) AS total_ways,
    
    'complete' AS download_status,
    CURRENT_TIMESTAMP AS downloaded_at,
    CURRENT_TIMESTAMP AS created_at,
    CURRENT_TIMESTAMP AS accessed_at
FROM (
    -- Get all unique tiles that have ways
    SELECT DISTINCT
        FLOOR(ST_XMin(geom)::NUMERIC / 0.05) * 0.05 AS tile_lon,
        FLOOR(ST_YMin(geom)::NUMERIC / 0.05) * 0.05 AS tile_lat
    FROM osm.ways
    WHERE geom IS NOT NULL
) AS tiles
ON CONFLICT (tile_key) DO UPDATE SET
    total_ways = EXCLUDED.total_ways,
    download_status = 'complete',
    downloaded_at = EXCLUDED.downloaded_at;
