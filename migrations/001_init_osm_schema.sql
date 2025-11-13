-- Migration 001: Initial schema for OSM road graph system
-- Date: 2025-11-13
-- Purpose: Create base tables for storing OSM road network data

-- Create osm schema
CREATE SCHEMA IF NOT EXISTS osm;

-- Table: osm.ways - Road segments
CREATE TABLE IF NOT EXISTS osm.ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL UNIQUE,
    geom geometry(LineString, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INTEGER,
    maxspeed VARCHAR(20),
    region VARCHAR(100) DEFAULT 'world',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: osm.nodes - Road network nodes (for routing)
CREATE TABLE IF NOT EXISTS osm.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL UNIQUE,
    geom geometry(Point, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: osm.cached_tiles - Tile-based cache for incremental downloads
CREATE TABLE IF NOT EXISTS osm.cached_tiles (
    id BIGSERIAL PRIMARY KEY,
    tile_key VARCHAR(50) NOT NULL UNIQUE,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    bbox geometry(Polygon, 4326) NOT NULL,
    total_ways INTEGER DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

-- Table: osm.regions - Named regions for bulk cache
CREATE TABLE IF NOT EXISTS osm.regions (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    bbox geometry(Polygon, 4326) NOT NULL,
    description TEXT,
    total_ways INTEGER DEFAULT 0,
    cached_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for osm.ways
CREATE INDEX IF NOT EXISTS idx_osm_ways_geom 
ON osm.ways USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_osm_ways_highway 
ON osm.ways USING BTREE(highway);

CREATE INDEX IF NOT EXISTS idx_osm_ways_tags 
ON osm.ways USING GIN(tags);

CREATE INDEX IF NOT EXISTS idx_osm_ways_region 
ON osm.ways USING BTREE(region);

-- Indexes for osm.nodes
CREATE INDEX IF NOT EXISTS idx_osm_nodes_geom 
ON osm.nodes USING GIST(geom);

-- Indexes for osm.cached_tiles
CREATE INDEX IF NOT EXISTS idx_cached_tiles_bbox 
ON osm.cached_tiles USING GIST(bbox);

CREATE INDEX IF NOT EXISTS idx_cached_tiles_tile_key 
ON osm.cached_tiles USING BTREE(tile_key);

-- Indexes for osm.regions
CREATE INDEX IF NOT EXISTS idx_regions_bbox 
ON osm.regions USING GIST(bbox);

-- Function: Check which tiles are cached
CREATE OR REPLACE FUNCTION osm.get_cached_tile_keys(tile_keys TEXT[])
RETURNS TABLE(tile_key TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT t.tile_key::TEXT
    FROM osm.cached_tiles t
    WHERE t.tile_key = ANY(tile_keys);
END;
$$ LANGUAGE plpgsql;

-- Function: Insert or update cached tile
CREATE OR REPLACE FUNCTION osm.upsert_cached_tile(
    p_tile_key VARCHAR,
    p_min_lon DOUBLE PRECISION,
    p_min_lat DOUBLE PRECISION,
    p_max_lon DOUBLE PRECISION,
    p_max_lat DOUBLE PRECISION,
    p_total_ways INTEGER
) RETURNS VOID AS $$
BEGIN
    INSERT INTO osm.cached_tiles (
        tile_key, min_lon, min_lat, max_lon, max_lat, 
        bbox, total_ways, accessed_at, access_count
    ) VALUES (
        p_tile_key, p_min_lon, p_min_lat, p_max_lon, p_max_lat,
        ST_MakeEnvelope(p_min_lon, p_min_lat, p_max_lon, p_max_lat, 4326),
        p_total_ways, CURRENT_TIMESTAMP, 1
    )
    ON CONFLICT (tile_key) DO UPDATE
    SET accessed_at = CURRENT_TIMESTAMP,
        access_count = osm.cached_tiles.access_count + 1;
END;
$$ LANGUAGE plpgsql;

-- Function: Get roads from cached tiles as GeoJSON
CREATE OR REPLACE FUNCTION osm.get_tiles_roads_geojson(tile_keys TEXT[])
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'type', 'FeatureCollection',
        'features', jsonb_agg(feature)
    ) INTO result
    FROM (
        SELECT jsonb_build_object(
            'type', 'Feature',
            'properties', jsonb_build_object(
                'way_id', w.osm_id,
                'highway', w.highway,
                'name', w.name,
                'lanes', w.lanes,
                'maxspeed', w.maxspeed,
                'surface', w.tags->>'surface'
            ),
            'geometry', ST_AsGeoJSON(w.geom)::jsonb
        ) AS feature
        FROM osm.ways w
        WHERE EXISTS (
            SELECT 1 FROM osm.cached_tiles t
            WHERE t.tile_key = ANY(tile_keys)
            AND ST_Intersects(w.geom, t.bbox)
        )
    ) features;
    
    RETURN COALESCE(result, '{"type":"FeatureCollection","features":[]}'::jsonb);
END;
$$ LANGUAGE plpgsql;

-- Verify schema
SELECT 
    'osm.ways' as table_name, COUNT(*) as row_count 
FROM osm.ways
UNION ALL
SELECT 
    'osm.nodes', COUNT(*) 
FROM osm.nodes
UNION ALL
SELECT 
    'osm.cached_tiles', COUNT(*) 
FROM osm.cached_tiles
UNION ALL
SELECT 
    'osm.regions', COUNT(*) 
FROM osm.regions;
