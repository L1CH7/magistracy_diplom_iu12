-- Migration 002: Create graph schema and tables for simulation
-- Purpose: Nodes and Edges tables with static/dynamic attributes
-- Date: 2025-11-10

-- Create graphs schema
CREATE SCHEMA IF NOT EXISTS graphs;

-- ============================================================================
-- NODES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS graphs.nodes (
    id SERIAL PRIMARY KEY,
    osm_node_id BIGINT UNIQUE NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    geometry GEOMETRY(POINT, 4326) NOT NULL,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Indexes
    CONSTRAINT nodes_lat_lon_check CHECK (
        lat BETWEEN -90 AND 90 AND 
        lon BETWEEN -180 AND 180
    )
);

-- Spatial index for fast bbox queries
CREATE INDEX IF NOT EXISTS idx_nodes_geometry ON graphs.nodes USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_nodes_osm_id ON graphs.nodes(osm_node_id);
CREATE INDEX IF NOT EXISTS idx_nodes_lat_lon ON graphs.nodes(lat, lon);

COMMENT ON TABLE graphs.nodes IS 'Graph nodes (intersections, endpoints)';
COMMENT ON COLUMN graphs.nodes.osm_node_id IS 'Original OSM node ID';
COMMENT ON COLUMN graphs.nodes.geometry IS 'PostGIS point geometry for spatial queries';

-- ============================================================================
-- EDGES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS graphs.edges (
    id SERIAL PRIMARY KEY,
    osm_way_id BIGINT NOT NULL,
    start_node_id INT NOT NULL REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    end_node_id INT NOT NULL REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    
    -- === STATIC ATTRIBUTES (не меняются) ===
    geometry GEOMETRY(LINESTRING, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL CHECK (length_m > 0),
    speed_limit_kmh DOUBLE PRECISION NOT NULL CHECK (speed_limit_kmh > 0),
    lanes INT NOT NULL CHECK (lanes > 0),
    oneway BOOLEAN DEFAULT false,
    highway_type VARCHAR(50) NOT NULL,
    
    -- OSM tags (JSONB для гибкости)
    osm_tags JSONB,
    
    -- === GENERATED COLUMNS (вычисляются автоматически) ===
    -- capacity = (length_m / 5.0) * lanes
    -- 5 метров на машину (длина авто + безопасное расстояние)
    capacity INT GENERATED ALWAYS AS (
        CAST(length_m / 5.0 AS INT) * lanes
    ) STORED,
    
    -- base_travel_time_sec = length_m / (speed_limit_kmh / 3.6)
    -- Время проезда при максимальной скорости без загруженности
    base_travel_time_sec DOUBLE PRECISION GENERATED ALWAYS AS (
        length_m / (speed_limit_kmh / 3.6)
    ) STORED,
    
    -- === DYNAMIC ATTRIBUTES (обновляются при симуляции) ===
    current_load INT DEFAULT 0 CHECK (current_load >= 0),
    effective_speed_kmh DOUBLE PRECISION,
    last_updated TIMESTAMP,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Unique constraint для предотвращения дублей
    UNIQUE(osm_way_id, start_node_id, end_node_id)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_edges_osm_way ON graphs.edges(osm_way_id);
CREATE INDEX IF NOT EXISTS idx_edges_start_node ON graphs.edges(start_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_end_node ON graphs.edges(end_node_id);
CREATE INDEX IF NOT EXISTS idx_edges_geometry ON graphs.edges USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_edges_highway_type ON graphs.edges(highway_type);
CREATE INDEX IF NOT EXISTS idx_edges_current_load ON graphs.edges(current_load);

COMMENT ON TABLE graphs.edges IS 'Graph edges (road segments with uniform characteristics)';
COMMENT ON COLUMN graphs.edges.osm_way_id IS 'Original OSM way ID (for deduplication)';
COMMENT ON COLUMN graphs.edges.capacity IS 'Max agents on edge = (length/5) × lanes';
COMMENT ON COLUMN graphs.edges.base_travel_time_sec IS 'Travel time at speed_limit with no congestion';
COMMENT ON COLUMN graphs.edges.current_load IS 'Current number of agents on this edge (updated by simulator)';
COMMENT ON COLUMN graphs.edges.effective_speed_kmh IS 'Current effective speed considering congestion';
COMMENT ON COLUMN graphs.edges.osm_tags IS 'Full OSM tags for future use (turn:lanes, maxspeed:conditional, etc)';

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View for edges with congestion ratio
DROP VIEW IF EXISTS edges_with_congestion CASCADE;
CREATE OR REPLACE VIEW edges_with_congestion AS
SELECT 
    e.*,
    CASE 
        WHEN e.capacity > 0 THEN e.current_load::FLOAT / e.capacity::FLOAT
        ELSE 0.0
    END as congestion_ratio
FROM graphs.edges e;

COMMENT ON VIEW edges_with_congestion IS 'Edges with calculated congestion_ratio = load/capacity';

-- View for adjacency list (для routing)
CREATE OR REPLACE VIEW adjacency_list AS
SELECT 
    start_node_id as node_id,
    array_agg(id) as outgoing_edge_ids
FROM graphs.edges
GROUP BY start_node_id;

COMMENT ON VIEW adjacency_list IS 'Adjacency list: node_id → array of outgoing edge IDs';

-- ============================================================================
-- STATISTICS
-- ============================================================================

-- Function to get graph statistics
CREATE OR REPLACE FUNCTION get_graph_stats()
RETURNS TABLE(
    total_nodes BIGINT,
    total_edges BIGINT,
    total_length_km DOUBLE PRECISION,
    avg_edge_length_m DOUBLE PRECISION,
    avg_lanes DOUBLE PRECISION,
    total_capacity BIGINT,
    highway_types JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (SELECT COUNT(*) FROM graphs.nodes),
        (SELECT COUNT(*) FROM graphs.edges),
        (SELECT SUM(length_m) / 1000.0 FROM graphs.edges),
        (SELECT AVG(length_m) FROM graphs.edges),
        (SELECT AVG(lanes) FROM graphs.edges),
        (SELECT SUM(capacity) FROM graphs.edges),
        (SELECT jsonb_object_agg(highway_type, cnt) 
         FROM (
             SELECT highway_type, COUNT(*) as cnt 
             FROM graphs.edges 
             GROUP BY highway_type
         ) sub
        );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_graph_stats() IS 'Get comprehensive graph statistics';

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

-- Grant permissions (если нужно)
-- GRANT SELECT, INSERT, UPDATE ON graphs.nodes, edges TO diplom;

-- Analyze tables for query optimization
ANALYZE graphs.nodes;
ANALYZE graphs.edges;
