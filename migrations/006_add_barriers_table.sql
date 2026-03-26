-- Migration 006: Add barriers table
-- Stores OSM barriers (gates, bollards, etc.) for routing

CREATE TABLE IF NOT EXISTS osm.barriers (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT NOT NULL,
    geom geometry(Geometry, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    barrier_type VARCHAR(50),
    type VARCHAR(10) NOT NULL, -- 'node' or 'way'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast spatial lookup
CREATE INDEX IF NOT EXISTS idx_osm_barriers_geom ON osm.barriers USING GIST(geom);
-- Index by osm_id
CREATE INDEX IF NOT EXISTS idx_osm_barriers_osm_id ON osm.barriers(osm_id);

COMMENT ON TABLE osm.barriers IS 'Stores point and line barriers from OSM data.';
