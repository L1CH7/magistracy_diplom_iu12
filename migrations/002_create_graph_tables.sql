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
    
    -- Node characteristics
    is_intersection BOOLEAN DEFAULT false,
    type VARCHAR(50) DEFAULT 'intersection',
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),
    barrier_penalty_sec INT DEFAULT 0,
    
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
    source INT NOT NULL REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    target INT NOT NULL REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    
    -- === STATIC ATTRIBUTES (не меняются) ===
    geometry GEOMETRY(LINESTRING, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL CHECK (length_m > 0),
    speed_limit_kmh DOUBLE PRECISION NOT NULL CHECK (speed_limit_kmh > 0),
    lanes INT NOT NULL CHECK (lanes > 0),
    oneway BOOLEAN DEFAULT false,
    highway_type VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    
    -- Access control
    access_type VARCHAR(50),
    is_restricted BOOLEAN DEFAULT false,
    barrier_penalty_sec INT DEFAULT 0,
    
    -- Additional attributes (from migration 024)
    bearing_start FLOAT,
    bearing_end FLOAT,
    motor_vehicle VARCHAR(50),
    service VARCHAR(50),
    
    -- OSM tags (JSONB для гибкости)
    osm_tags JSONB,
    
    -- === TRAFFIC LOAD ===
    base_capacity INT NOT NULL DEFAULT 1000,
    current_load INT DEFAULT 0 CHECK (current_load >= 0),
    
    -- === GENERATED COLUMNS (вычисляются автоматически) ===
    -- Effective speed considering traffic load (BPR function)
    effective_speed_kmh DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE
            WHEN current_load = 0 THEN speed_limit_kmh
            WHEN current_load <= base_capacity THEN speed_limit_kmh
            ELSE GREATEST(5.0, speed_limit_kmh * (2.0 - current_load::FLOAT / base_capacity))
        END
    ) STORED,
    
    -- Travel time (cost) in seconds
    cost DOUBLE PRECISION GENERATED ALWAYS AS (
        length_m / (
            CASE
                WHEN current_load = 0 THEN speed_limit_kmh
                WHEN current_load <= base_capacity THEN speed_limit_kmh
                ELSE GREATEST(5.0, speed_limit_kmh * (2.0 - current_load::FLOAT / base_capacity))
            END / 3.6
        )
    ) STORED,
    
    -- Reverse cost (-1 for oneway)
    reverse_cost DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE
            WHEN oneway THEN -1.0
            ELSE length_m / (
                CASE
                    WHEN current_load = 0 THEN speed_limit_kmh
                    WHEN current_load <= base_capacity THEN speed_limit_kmh
                    ELSE GREATEST(5.0, speed_limit_kmh * (2.0 - current_load::FLOAT / base_capacity))
                END / 3.6
            )
        END
    ) STORED,
    
    -- Metadata
    last_updated TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Unique constraint для предотвращения дублей
    UNIQUE(osm_way_id, source, target)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_edges_osm_way ON graphs.edges(osm_way_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON graphs.edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON graphs.edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_geometry ON graphs.edges USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_edges_highway_type ON graphs.edges(highway_type);
CREATE INDEX IF NOT EXISTS idx_edges_current_load ON graphs.edges(current_load);
CREATE INDEX IF NOT EXISTS idx_edges_motor_vehicle ON graphs.edges(motor_vehicle) WHERE motor_vehicle IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_edges_service ON graphs.edges(service) WHERE service IS NOT NULL;

COMMENT ON TABLE graphs.edges IS 'Graph edges (road segments for routing)';
COMMENT ON COLUMN graphs.edges.osm_way_id IS 'Original OSM way ID';
COMMENT ON COLUMN graphs.edges.source IS 'Start node ID';
COMMENT ON COLUMN graphs.edges.target IS 'End node ID';
COMMENT ON COLUMN graphs.edges.base_capacity IS 'Maximum vehicles per hour (static)';
COMMENT ON COLUMN graphs.edges.current_load IS 'Current number of agents on edge';
COMMENT ON COLUMN graphs.edges.effective_speed_kmh IS 'Effective speed considering traffic load';
COMMENT ON COLUMN graphs.edges.cost IS 'Travel time in seconds (dynamic based on load)';
COMMENT ON COLUMN graphs.edges.reverse_cost IS 'Reverse cost (-1 for oneway streets)';
COMMENT ON COLUMN graphs.edges.access_type IS 'Access restriction type (public, private, destination, no)';
COMMENT ON COLUMN graphs.edges.barrier_penalty_sec IS 'Time penalty for barriers in seconds';
COMMENT ON COLUMN graphs.edges.bearing_start IS 'Bearing at edge start (degrees, 0-360)';
COMMENT ON COLUMN graphs.edges.bearing_end IS 'Bearing at edge end (degrees, 0-360)';
COMMENT ON COLUMN graphs.edges.motor_vehicle IS 'Motor vehicle access (yes, no, destination, private)';
COMMENT ON COLUMN graphs.edges.service IS 'Service type (driveway, parking, alley, parking_aisle)';
COMMENT ON COLUMN graphs.edges.osm_tags IS 'Full OSM tags for future use';

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View for edges with congestion ratio
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
    source as node_id,
    array_agg(id) as outgoing_edge_ids
FROM graphs.edges
GROUP BY source;

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
