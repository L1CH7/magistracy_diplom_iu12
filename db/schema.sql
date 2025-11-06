-- PostGIS schema for road graph caching
-- Optimized for bbox queries and GeoJSON export

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- OSM Ways table (road segments)
CREATE TABLE IF NOT EXISTS osm_ways (
    id BIGSERIAL PRIMARY KEY,
    
    -- OSM identification
    osm_id BIGINT NOT NULL UNIQUE,
    
    -- Geometry (LineString in WGS84)
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    
    -- OSM tags (JSONB for fast queries)
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    
    -- Precomputed fields for fast filtering
    highway VARCHAR(50) NOT NULL,  -- Indexed for filtering
    name VARCHAR(255),
    lanes INTEGER,
    maxspeed VARCHAR(20),
    oneway BOOLEAN DEFAULT FALSE,
    
    -- Region tracking
    region VARCHAR(100) DEFAULT 'unknown',
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- OSM Nodes table (for topology, optional)
CREATE TABLE IF NOT EXISTS osm_nodes (
    id BIGSERIAL PRIMARY KEY,
    
    -- OSM identification
    osm_id BIGINT NOT NULL UNIQUE,
    
    -- Geometry (Point in WGS84)
    geom GEOMETRY(POINT, 4326) NOT NULL,
    
    -- Tags (if any)
    tags JSONB DEFAULT '{}'::jsonb,
    
    -- Region tracking
    region VARCHAR(100) DEFAULT 'unknown',
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Cached regions metadata
CREATE TABLE IF NOT EXISTS cached_regions (
    id SERIAL PRIMARY KEY,
    
    -- Region identification
    region_name VARCHAR(100) NOT NULL UNIQUE,
    
    -- Bounding box (for quick lookup)
    bbox GEOMETRY(POLYGON, 4326) NOT NULL,
    
    -- Statistics
    total_ways INTEGER DEFAULT 0,
    total_nodes INTEGER DEFAULT 0,
    total_elements INTEGER DEFAULT 0,
    
    -- Status
    is_complete BOOLEAN DEFAULT FALSE,
    fetch_started_at TIMESTAMP,
    fetch_completed_at TIMESTAMP,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance

-- Spatial index on ways (GIST for bbox queries)
CREATE INDEX IF NOT EXISTS idx_osm_ways_geom 
    ON osm_ways USING GIST(geom);

-- Index on highway type (for filtering drivable roads)
CREATE INDEX IF NOT EXISTS idx_osm_ways_highway 
    ON osm_ways(highway);

-- Index on region (for bulk queries)
CREATE INDEX IF NOT EXISTS idx_osm_ways_region 
    ON osm_ways(region);

-- JSONB GIN index for tag queries
CREATE INDEX IF NOT EXISTS idx_osm_ways_tags 
    ON osm_ways USING GIN(tags);

-- Spatial index on nodes
CREATE INDEX IF NOT EXISTS idx_osm_nodes_geom 
    ON osm_nodes USING GIST(geom);

-- Spatial index on cached regions bbox
CREATE INDEX IF NOT EXISTS idx_cached_regions_bbox 
    ON cached_regions USING GIST(bbox);

-- Helper function: Get GeoJSON for a bbox
CREATE OR REPLACE FUNCTION get_roads_geojson(
    min_lon FLOAT,
    min_lat FLOAT,
    max_lon FLOAT,
    max_lat FLOAT
) RETURNS JSON AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', json_agg(
            json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geom)::json,
                'properties', json_build_object(
                    'way_id', osm_id,
                    'highway', highway,
                    'name', name,
                    'lanes', lanes,
                    'maxspeed', maxspeed,
                    'oneway', oneway
                ) || tags  -- Merge with all OSM tags
            )
        )
    ) INTO result
    FROM osm_ways
    WHERE ST_Intersects(
        geom,
        ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    );
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Helper function: Insert way with geometry from coordinates
CREATE OR REPLACE FUNCTION insert_way(
    p_osm_id BIGINT,
    p_coordinates JSON,  -- [[lon, lat], [lon, lat], ...]
    p_tags JSONB,
    p_region VARCHAR DEFAULT 'unknown'
) RETURNS VOID AS $$
DECLARE
    v_highway VARCHAR;
    v_linestring GEOMETRY;
BEGIN
    -- Extract highway type
    v_highway := p_tags->>'highway';
    
    -- Build LineString from coordinates
    v_linestring := ST_GeomFromGeoJSON(
        json_build_object(
            'type', 'LineString',
            'coordinates', p_coordinates
        )::text
    );
    
    -- Insert or update
    INSERT INTO osm_ways (
        osm_id, geom, tags, highway, name, lanes, maxspeed, oneway, region
    ) VALUES (
        p_osm_id,
        v_linestring,
        p_tags,
        v_highway,
        p_tags->>'name',
        (p_tags->>'lanes')::INTEGER,
        p_tags->>'maxspeed',
        COALESCE((p_tags->>'oneway')::BOOLEAN, FALSE),
        p_region
    )
    ON CONFLICT (osm_id) DO UPDATE SET
        geom = EXCLUDED.geom,
        tags = EXCLUDED.tags,
        highway = EXCLUDED.highway,
        name = EXCLUDED.name,
        lanes = EXCLUDED.lanes,
        maxspeed = EXCLUDED.maxspeed,
        oneway = EXCLUDED.oneway,
        region = EXCLUDED.region,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Helper function: Check if region is cached
CREATE OR REPLACE FUNCTION is_region_cached(p_region_name VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM cached_regions 
        WHERE region_name = p_region_name AND is_complete = TRUE
    );
END;
$$ LANGUAGE plpgsql;
