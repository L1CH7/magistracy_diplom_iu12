-- Migration 003: Create graphs.nodes table
-- Date: 2025-11-28
-- Purpose: Store graph nodes (intersections, barriers, endpoints)

CREATE TABLE graphs.nodes (
    id SERIAL PRIMARY KEY,
    osm_node_id BIGINT UNIQUE,
    
    -- Geometry
    geom GEOMETRY(Point, 4326) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    
    -- Node type
    type VARCHAR(50) DEFAULT 'intersection',
    -- Types: 'intersection', 'uturn', 'barrier', 'traffic_signal', 'endpoint'
    
    -- Intersection info
    is_intersection BOOLEAN DEFAULT false,
    
    -- Barrier info
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),
    barrier_penalty_sec INT DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== INDEXES ====================
CREATE INDEX idx_nodes_geom ON graphs.nodes USING GIST(geom);
CREATE INDEX idx_nodes_type ON graphs.nodes(type);
CREATE INDEX idx_nodes_osm_id ON graphs.nodes(osm_node_id);
CREATE INDEX idx_nodes_intersection ON graphs.nodes(is_intersection) WHERE is_intersection = true;

-- ==================== COMMENTS ====================
COMMENT ON TABLE graphs.nodes IS 'Graph nodes: intersections, barriers, endpoints';
COMMENT ON COLUMN graphs.nodes.type IS 'Node type: intersection/uturn/barrier/traffic_signal/endpoint';
COMMENT ON COLUMN graphs.nodes.is_intersection IS 'True if node connects 2+ edges';
