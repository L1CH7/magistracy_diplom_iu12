-- Create processed GeoJSON cache table
-- This stores filtered and classified GeoJSON for instant loading

CREATE TABLE IF NOT EXISTS graphs.processed_geojson (
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    style_version VARCHAR(50) NOT NULL DEFAULT 'v1',
    data JSONB NOT NULL,
    feature_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    PRIMARY KEY (min_lon, min_lat, max_lon, max_lat, style_version)
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_processed_geojson_bbox 
    ON graphs.processed_geojson 
    USING GIST (
        ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
    );

-- Index on version for cache invalidation
CREATE INDEX IF NOT EXISTS idx_processed_geojson_version
    ON graphs.processed_geojson (style_version);

COMMENT ON TABLE graphs.processed_geojson IS 
    'Cache for processed (filtered + classified) GeoJSON to eliminate client-side processing delays';
    
COMMENT ON COLUMN graphs.processed_geojson.style_version IS 
    'Style version identifier - increment to invalidate cache when classification logic changes';
