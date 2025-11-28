-- Migration 001: Initial OSM schema (raw OSM data)
-- Date: 2025-11-28
-- Purpose: Create tables for storing raw OSM data (source of truth)

CREATE SCHEMA IF NOT EXISTS osm;

-- ==================== OSM WAYS (roads, paths) ====================
CREATE TABLE osm.ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    geom_3857 GEOMETRY(LineString, 3857),  -- Web Mercator for MVT
    tags JSONB NOT NULL DEFAULT '{}',
    
    -- Core attributes (extracted for indexing)
    highway VARCHAR(50),
    name VARCHAR(255),
    lanes INT,
    maxspeed VARCHAR(20),
    oneway TEXT,
    access TEXT,
    motor_vehicle TEXT,
    service TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== OSM NODES ====================
CREATE TABLE osm.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== OSM BARRIERS ====================
CREATE TABLE osm.barriers (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    geom GEOMETRY(Point, 4326) NOT NULL,
    barrier_type VARCHAR(50) NOT NULL,
    access VARCHAR(50),
    motor_vehicle VARCHAR(50),
    name VARCHAR(255),
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== CACHED TILES ====================
CREATE TABLE osm.cached_tiles (
    id BIGSERIAL PRIMARY KEY,
    tile_key VARCHAR(50) UNIQUE NOT NULL,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    bbox GEOMETRY(Polygon, 4326) NOT NULL,
    total_ways INT DEFAULT 0,
    
    -- Download tracking
    download_status TEXT DEFAULT 'pending',
    download_error TEXT,
    download_attempts INT DEFAULT 0,
    last_download_attempt TIMESTAMP,
    downloaded_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INT DEFAULT 0
);

-- ==================== INDEXES ====================
CREATE INDEX idx_osm_ways_geom ON osm.ways USING GIST(geom);
CREATE INDEX idx_osm_ways_geom_3857 ON osm.ways USING GIST(geom_3857);
CREATE INDEX idx_osm_ways_highway ON osm.ways(highway) WHERE highway IS NOT NULL;
CREATE INDEX idx_osm_ways_tags ON osm.ways USING GIN(tags);

CREATE INDEX idx_osm_nodes_geom ON osm.nodes USING GIST(geom);

CREATE INDEX idx_osm_barriers_geom ON osm.barriers USING GIST(geom);
CREATE INDEX idx_osm_barriers_type ON osm.barriers(barrier_type);

CREATE INDEX idx_cached_tiles_bbox ON osm.cached_tiles USING GIST(bbox);
CREATE INDEX idx_cached_tiles_status ON osm.cached_tiles(download_status);

-- ==================== TRIGGER: Auto-sync geom_3857 ====================
CREATE OR REPLACE FUNCTION osm.sync_geom_3857()
RETURNS TRIGGER AS $$
BEGIN
    NEW.geom_3857 := ST_Transform(NEW.geom, 3857);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ways_sync_3857
BEFORE INSERT OR UPDATE ON osm.ways
FOR EACH ROW
EXECUTE FUNCTION osm.sync_geom_3857();

-- Generic timestamp update function (reusable)
CREATE OR REPLACE FUNCTION osm.update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
