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
            maxspeed = EXCLUDED.maxspeed
    """

    BATCH_INSERT_NODES = """
        INSERT INTO osm.nodes (
            osm_id, geom, tags
        ) VALUES (
            $1, ST_SetSRID(ST_Point($2, $3), 4326), $4::jsonb
        )
        ON CONFLICT (osm_id) DO UPDATE SET
            geom = EXCLUDED.geom,
            tags = EXCLUDED.tags
    """

    BATCH_INSERT_TURN_RESTRICTIONS = """
        INSERT INTO osm.turn_restrictions (
            osm_id, tags, members
        ) VALUES (
            $1, $2::jsonb, $3::jsonb
        )
        ON CONFLICT (osm_id) DO UPDATE SET
            tags = EXCLUDED.tags,
            members = EXCLUDED.members
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
        SELECT ST_AsMVT(tile, 'ways', 4096, 'geom', 'id')
        FROM (
            SELECT
                id,
                highway,
                name,
                tags->>'oneway' AS oneway,
                maxspeed,
                ST_AsMVTGeom(
                    geom_3857,
                    ST_TileEnvelope($1, $2, $3),
                    4096,
                    256,
                    true
                ) AS geom
            FROM osm.ways
            WHERE 
                -- Expand selection envelope by buffer margin (0.125 = 1/8 tile size ~= 512 units)
                -- ST_AsMVTGeom buffer is 256 units (0.0625). We use double that to be safe.
                geom_3857 && ST_TileEnvelope($1, $2, $3, margin => 0.125)
                AND highway IS NOT NULL
                -- Dynamic LOD Filter
                -- $4 contains the array of allowed highway types for this zoom
                -- If $4 is NULL or empty, it might mean "show nothing" or "show all"?
                -- Logic: If 'ALL' is in the array, show everything.
                -- Otherwise, filter by array.
                AND (
                    'ALL' = ANY($4::text[])
                    OR highway = ANY($4::text[])
                )
                ORDER BY
                    CASE highway
                        WHEN 'motorway' THEN 10
                        WHEN 'trunk' THEN 9
                        WHEN 'primary' THEN 8
                        WHEN 'secondary' THEN 7
                        WHEN 'tertiary' THEN 6
                        WHEN 'unclassified' THEN 5
                        WHEN 'residential' THEN 4
                        WHEN 'service' THEN 3
                        WHEN 'track' THEN 2
                        WHEN 'path' THEN 1
                        WHEN 'footway' THEN 1
                        ELSE 0
                    END ASC
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

    # ==================== Index Management ====================

    # DROP INDEXES
    DROP_INDEXES_WAYS = [
        "DROP INDEX IF EXISTS osm.idx_osm_ways_geom",
        "DROP INDEX IF EXISTS osm.idx_osm_ways_geom_3857",
        "DROP INDEX IF EXISTS osm.idx_osm_ways_highway",
        "DROP INDEX IF EXISTS osm.idx_osm_ways_region",
        "DROP INDEX IF EXISTS osm.idx_osm_ways_tags",
        "ALTER TABLE osm.ways DROP CONSTRAINT IF EXISTS ways_osm_id_key"
    ]

    DROP_INDEXES_NODES = [
        "DROP INDEX IF EXISTS osm.idx_osm_nodes_geom",
        "ALTER TABLE osm.nodes DROP CONSTRAINT IF EXISTS nodes_osm_id_key"
    ]

    DROP_INDEXES_BARRIERS = [
        "DROP INDEX IF EXISTS osm.idx_osm_barriers_geom",
        "DROP INDEX IF EXISTS osm.idx_osm_barriers_osm_id",
        "ALTER TABLE osm.barriers DROP CONSTRAINT IF EXISTS osm_barriers_pk"
    ]

    # CREATE INDEXES
    CREATE_INDEXES_WAYS = [
        "CREATE INDEX IF NOT EXISTS idx_osm_ways_geom ON osm.ways USING GIST(geom)",
        "CREATE INDEX IF NOT EXISTS idx_osm_ways_geom_3857 ON osm.ways USING GIST(geom_3857)",
        "CREATE INDEX IF NOT EXISTS idx_osm_ways_highway ON osm.ways USING BTREE(highway)",
        "CREATE INDEX IF NOT EXISTS idx_osm_ways_region ON osm.ways USING BTREE(region)",
        "CREATE INDEX IF NOT EXISTS idx_osm_ways_tags ON osm.ways USING GIN(tags)",
        "ALTER TABLE osm.ways ADD CONSTRAINT ways_osm_id_key UNIQUE (osm_id)"
    ]

    CREATE_INDEXES_NODES = [
        "CREATE INDEX IF NOT EXISTS idx_osm_nodes_geom ON osm.nodes USING GIST(geom)",
        "ALTER TABLE osm.nodes ADD CONSTRAINT nodes_osm_id_key UNIQUE (osm_id)"
    ]

    CREATE_INDEXES_BARRIERS = [
        "CREATE INDEX IF NOT EXISTS idx_osm_barriers_geom ON osm.barriers USING GIST(geom)",
        "CREATE INDEX IF NOT EXISTS idx_osm_barriers_osm_id ON osm.barriers USING BTREE(osm_id)",
        "ALTER TABLE osm.barriers ADD CONSTRAINT osm_barriers_pk UNIQUE (osm_id, type)"
    ]


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
