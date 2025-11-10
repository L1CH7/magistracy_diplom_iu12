-- PostGIS multi-schema database for tiles, OSM data, and graphs
-- Three separate schemas for clear separation and future scalability

CREATE EXTENSION IF NOT EXISTS postgis;

-- ===========================================================================
-- SCHEMA 1: tiles - raster map tile caching
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS tiles;

CREATE TABLE IF NOT EXISTS tiles.raster_tiles (
    id BIGSERIAL PRIMARY KEY,
    z SMALLINT NOT NULL CHECK (z >= 0 AND z <= 20),
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    tile_data BYTEA NOT NULL,
    source VARCHAR(50) DEFAULT 'osm',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    UNIQUE(z, x, y, source)
);

CREATE INDEX idx_tiles_zxy ON tiles.raster_tiles(z, x, y);
CREATE INDEX idx_tiles_source ON tiles.raster_tiles(source);
CREATE INDEX idx_tiles_accessed ON tiles.raster_tiles(accessed_at);

-- Function to get tile (updates access stats)
CREATE OR REPLACE FUNCTION tiles.get_tile(
    _z SMALLINT,
    _x INTEGER,
    _y INTEGER,
    _source VARCHAR DEFAULT 'osm'
)
RETURNS BYTEA AS $$
DECLARE
    tile_bytes BYTEA;
BEGIN
    UPDATE tiles.raster_tiles
    SET accessed_at = NOW(),
        access_count = access_count + 1
    WHERE z = _z AND x = _x AND y = _y AND source = _source
    RETURNING tile_data INTO tile_bytes;
    
    RETURN tile_bytes;
END;
$$ LANGUAGE plpgsql;

-- Function to insert tile
CREATE OR REPLACE FUNCTION tiles.insert_tile(
    _z SMALLINT,
    _x INTEGER,
    _y INTEGER,
    _data BYTEA,
    _source VARCHAR DEFAULT 'osm'
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO tiles.raster_tiles (z, x, y, tile_data, source)
    VALUES (_z, _x, _y, _data, _source)
    ON CONFLICT (z, x, y, source)
    DO UPDATE SET
        tile_data = EXCLUDED.tile_data,
        accessed_at = NOW(),
        access_count = tiles.raster_tiles.access_count + 1;
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- SCHEMA 2: osm - raw OSM data cache
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS osm;

-- OSM ways (road segments)
CREATE TABLE IF NOT EXISTS osm.ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL UNIQUE,
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INTEGER,
    maxspeed VARCHAR(20),
    region VARCHAR(100) DEFAULT 'world',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- OSM nodes (intersections)
CREATE TABLE IF NOT EXISTS osm.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL UNIQUE,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    tags JSONB DEFAULT '{}'::jsonb,
    region VARCHAR(100) DEFAULT 'world',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Regions tracking (which areas are cached)
CREATE TABLE IF NOT EXISTS osm.regions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    bbox GEOMETRY(POLYGON, 4326) NOT NULL,
    total_ways INTEGER DEFAULT 0,
    total_elements INTEGER DEFAULT 0,
    is_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Spatial indexes (GIST for geometry queries)
CREATE INDEX idx_osm_ways_geom ON osm.ways USING GIST(geom);
CREATE INDEX idx_osm_ways_highway ON osm.ways(highway);
CREATE INDEX idx_osm_ways_region ON osm.ways(region);
CREATE INDEX idx_osm_ways_tags ON osm.ways USING GIN(tags);
CREATE INDEX idx_osm_nodes_geom ON osm.nodes USING GIST(geom);
CREATE INDEX idx_osm_regions_bbox ON osm.regions USING GIST(bbox);

-- Function to check if region is cached
CREATE OR REPLACE FUNCTION osm.is_region_cached(_region_name VARCHAR)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM osm.regions
        WHERE name = _region_name AND is_complete = TRUE
    );
END;
$$ LANGUAGE plpgsql;

-- Function to get roads as GeoJSON
CREATE OR REPLACE FUNCTION osm.get_roads_geojson(
    min_lon DOUBLE PRECISION,
    min_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION
)
RETURNS JSON AS $$
BEGIN
    RETURN json_build_object(
        'type', 'FeatureCollection',
        'features', COALESCE((
            SELECT json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', json_build_object(
                        'way_id', osm_id,
                        'highway', highway,
                        'name', name,
                        'lanes', lanes,
                        'maxspeed', maxspeed
                    )::jsonb || tags  -- Merge tags (convert json to jsonb)
                )
            )
            FROM osm.ways
            WHERE ST_Intersects(
                geom,
                ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
            )
        ), '[]'::json)
    );
END;
$$ LANGUAGE plpgsql;

-- Function to bulk insert ways
CREATE OR REPLACE FUNCTION osm.insert_way(
    _osm_id BIGINT,
    _coordinates JSON,  -- [[lon, lat], [lon, lat], ...]
    _tags JSONB,
    _region VARCHAR DEFAULT 'world'
)
RETURNS VOID AS $$
DECLARE
    _highway VARCHAR;
    _name VARCHAR;
    _lanes INTEGER;
    _maxspeed VARCHAR;
BEGIN
    -- Extract common tags
    _highway := _tags->>'highway';
    _name := _tags->>'name';
    _lanes := (_tags->>'lanes')::INTEGER;
    _maxspeed := _tags->>'maxspeed';
    
    -- Insert or update
    INSERT INTO osm.ways (osm_id, geom, tags, highway, name, lanes, maxspeed, region)
    VALUES (
        _osm_id,
        ST_GeomFromGeoJSON(json_build_object(
            'type', 'LineString',
            'coordinates', _coordinates
        )::text),
        _tags,
        _highway,
        _name,
        _lanes,
        _maxspeed,
        _region
    )
    ON CONFLICT (osm_id)
    DO UPDATE SET
        geom = EXCLUDED.geom,
        tags = EXCLUDED.tags,
        highway = EXCLUDED.highway,
        name = EXCLUDED.name,
        lanes = EXCLUDED.lanes,
        maxspeed = EXCLUDED.maxspeed,
        region = EXCLUDED.region;
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- SCHEMA 3: graphs - processed routing graphs
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS graphs;

-- Graph nodes (routing network)
CREATE TABLE IF NOT EXISTS graphs.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_node_id BIGINT,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    region VARCHAR(100) DEFAULT 'world',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Graph edges (connections)
CREATE TABLE IF NOT EXISTS graphs.edges (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES graphs.nodes(id),
    target_id BIGINT NOT NULL REFERENCES graphs.nodes(id),
    osm_way_id BIGINT,
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    highway VARCHAR(50),
    length_m DOUBLE PRECISION,
    time_s DOUBLE PRECISION,
    tags JSONB DEFAULT '{}'::jsonb,
    region VARCHAR(100) DEFAULT 'world',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cached routes (reusable)
CREATE TABLE IF NOT EXISTS graphs.routes (
    id BIGSERIAL PRIMARY KEY,
    from_node_id BIGINT NOT NULL,
    to_node_id BIGINT NOT NULL,
    edge_sequence BIGINT[] NOT NULL,
    total_distance_m DOUBLE PRECISION,
    total_time_s DOUBLE PRECISION,
    geom GEOMETRY(LINESTRING, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    CHECK (array_length(edge_sequence, 1) > 0)
);

-- Indexes for graphs
CREATE INDEX idx_graphs_nodes_geom ON graphs.nodes USING GIST(geom);
CREATE INDEX idx_graphs_nodes_region ON graphs.nodes(region);
CREATE INDEX idx_graphs_edges_source ON graphs.edges(source_id);
CREATE INDEX idx_graphs_edges_target ON graphs.edges(target_id);
CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geom);
CREATE INDEX idx_graphs_routes_from_to ON graphs.routes(from_node_id, to_node_id);
CREATE INDEX idx_graphs_routes_accessed ON graphs.routes(accessed_at);

-- ===========================================================================
-- Statistics and monitoring
-- ===========================================================================

CREATE OR REPLACE FUNCTION public.get_db_stats()
RETURNS JSON AS $$
BEGIN
    RETURN json_build_object(
        'tiles', json_build_object(
            'total', (SELECT COUNT(*) FROM tiles.raster_tiles),
            'sources', (SELECT json_object_agg(source, cnt) FROM (
                SELECT source, COUNT(*) as cnt
                FROM tiles.raster_tiles
                GROUP BY source
            ) s)
        ),
        'osm', json_build_object(
            'ways', (SELECT COUNT(*) FROM osm.ways),
            'nodes', (SELECT COUNT(*) FROM osm.nodes),
            'regions', (SELECT COUNT(*) FROM osm.regions),
            'complete_regions', (SELECT COUNT(*) FROM osm.regions WHERE is_complete = TRUE)
        ),
        'graphs', json_build_object(
            'nodes', (SELECT COUNT(*) FROM graphs.nodes),
            'edges', (SELECT COUNT(*) FROM graphs.edges),
            'cached_routes', (SELECT COUNT(*) FROM graphs.routes)
        )
    );
END;
$$ LANGUAGE plpgsql;
