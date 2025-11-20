"""
SQL queries for OSM data operations.
Centralized query management for better maintainability.
"""

from typing import Tuple, Optional


class OSMQueries:
    """SQL queries for OSM data management."""
    
    # ==================== OSM Ways ====================
    
    BATCH_INSERT_WAYS = """
        INSERT INTO osm.ways (
            osm_id, geom, geom_3857, tags, highway, name, lanes, maxspeed
        ) VALUES (
            $1,
            ST_GeomFromGeoJSON($2),
            ST_Transform(ST_GeomFromGeoJSON($2), 3857),
            $3::jsonb,
            $4, $5, $6::integer, $7
        )
        ON CONFLICT (osm_id) DO UPDATE SET
            geom = EXCLUDED.geom,
            geom_3857 = EXCLUDED.geom_3857,
            tags = EXCLUDED.tags,
            highway = EXCLUDED.highway,
            name = EXCLUDED.name,
            lanes = EXCLUDED.lanes,
            maxspeed = EXCLUDED.maxspeed,
            updated_at = NOW()
    """
    
    COUNT_WAYS_IN_BBOX = """
        SELECT COUNT(*)
        FROM osm.ways
        WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
    """
    
    DELETE_WAYS_IN_BBOX = """
        DELETE FROM osm.ways
        WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
    """
    
    # ==================== Cached Tiles ====================
    
    GET_TILE_STATUS = """
        SELECT
            tile_key,
            download_status,
            total_ways,
            download_error,
            download_attempts,
            created_at,
            last_download_attempt
        FROM osm.cached_tiles
        WHERE tile_key = $1
    """
    
    INSERT_TILE_METADATA = """
        INSERT INTO osm.cached_tiles (
            tile_key,
            download_status,
            total_ways,
            min_lon, min_lat, max_lon, max_lat,
            bbox
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            ST_MakeEnvelope($4, $5, $6, $7, 4326)
        )
        ON CONFLICT (tile_key) DO UPDATE SET
            download_status = EXCLUDED.download_status,
            total_ways = EXCLUDED.total_ways,
            last_download_attempt = NOW()
    """
    
    UPDATE_TILE_STATUS = """
        UPDATE osm.cached_tiles
        SET download_status = $2,
            total_ways = $3,
            download_error = $4,
            download_attempts = COALESCE(download_attempts, 0) + 1,
            last_download_attempt = NOW(),
            downloaded_at = CASE WHEN $2 = 'complete'
                THEN NOW() ELSE NULL END
        WHERE tile_key = $1
    """
    
    MARK_TILE_FAILED = """
        UPDATE osm.cached_tiles
        SET download_status = 'failed',
            download_error = $2,
            download_attempts = COALESCE(download_attempts, 0) + 1,
            last_download_attempt = NOW()
        WHERE tile_key = $1
    """
    
    RESET_TILE_FOR_REDOWNLOAD = """
        UPDATE osm.cached_tiles
        SET download_status = 'pending',
            download_error = NULL,
            download_attempts = 0,
            last_download_attempt = NULL
        WHERE tile_key = $1
        RETURNING tile_key
    """
    
    # ==================== Recovery ====================
    
    FIND_STUCK_TILES = """
        SELECT tile_key, last_download_attempt
        FROM osm.cached_tiles
        WHERE download_status = 'downloading'
          AND last_download_attempt < NOW() - INTERVAL '5 minutes'
    """
    
    RESET_STUCK_TILE = """
        UPDATE osm.cached_tiles
        SET download_status = 'failed',
            download_error = 'Interrupted by restart'
        WHERE tile_key = $1
    """
    
    # ==================== MVT Generation ====================
    
    GENERATE_MVT_TILE = """
        SELECT ST_AsMVT(tile, 'roads', 4096, 'geom')
        FROM (
            SELECT
                osm_id,
                jsonb_build_object(
                    'highway', highway,
                    'name', name,
                    'oneway', tags->>'oneway',
                    'maxspeed', maxspeed
                ) AS properties,
                ST_AsMVTGeom(
                    geom_3857,
                    ST_TileEnvelope($1, $2, $3),
                    4096,
                    256,
                    true
                ) AS geom
            FROM osm.ways
            WHERE 
                geom_3857 && ST_TileEnvelope($1, $2, $3)
                AND highway IS NOT NULL
                -- Filter by zoom level
                AND (
                    $1 >= 14 
                    OR highway IN (
                        'motorway', 'trunk', 'primary', 
                        'motorway_link', 'trunk_link', 'primary_link'
                    )
                )
        ) AS tile
        WHERE geom IS NOT NULL
    """
    
    # ==================== Statistics ====================
    
    GET_WAYS_COUNT = """
        SELECT COUNT(*) FROM osm.ways
    """
    
    GET_CACHED_TILES_COUNT = """
        SELECT COUNT(*) FROM osm.cached_tiles
        WHERE download_status = 'complete'
    """
    
    GET_DOWNLOADING_TILES_COUNT = """
        SELECT COUNT(*) FROM osm.cached_tiles
        WHERE download_status = 'downloading'
    """
    
    GET_FAILED_TILES_COUNT = """
        SELECT COUNT(*) FROM osm.cached_tiles
        WHERE download_status = 'failed'
    """
    
    GET_FAILED_TILES = """
        SELECT
            tile_key,
            download_error,
            download_attempts,
            last_download_attempt
        FROM osm.cached_tiles
        WHERE download_status = 'failed'
        ORDER BY last_download_attempt DESC
        LIMIT $1
    """
    
    # ==================== Preload Cache ====================
    
    PRELOAD_CACHED_TILES = """
        SELECT
            tile_key,
            download_status,
            total_ways,
            min_lon, min_lat, max_lon, max_lat,
            downloaded_at
        FROM osm.cached_tiles
        WHERE download_status = 'complete'
    """


def parse_tile_key(tile_key: str) -> Optional[Tuple[float, float]]:
    """
    Parse tile_key string to (lon, lat) tuple.
    
    Args:
        tile_key: "37.60_55.75" or "monolith"
    
    Returns:
        (lon, lat) or None for monolith
    """
    if tile_key == "monolith":
        return None
    
    try:
        lon_str, lat_str = tile_key.split('_')
        return (float(lon_str), float(lat_str))
    except (ValueError, AttributeError):
        return None


def format_tile_key(lon: float, lat: float) -> str:
    """
    Format (lon, lat) to tile_key string.
    
    Args:
        lon: Longitude
        lat: Latitude
    
    Returns:
        "37.60_55.75"
    """
    return f"{lon:.2f}_{lat:.2f}"
