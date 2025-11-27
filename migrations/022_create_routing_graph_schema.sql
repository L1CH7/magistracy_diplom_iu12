-- Migration: Create routing_graph schema for pgRouting
-- Date: 2025-11-27
-- Purpose: Separate routing graph from raw OSM data

-- Create graphs schema
CREATE SCHEMA IF NOT EXISTS graphs;

-- Nodes table (intersections and road endpoints)
CREATE TABLE IF NOT EXISTS graphs.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_node_id BIGINT,
    geom GEOMETRY(Point, 4326) NOT NULL,
    is_intersection BOOLEAN DEFAULT false,
    type VARCHAR(50) DEFAULT 'intersection',
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_graphs_nodes_geom
ON graphs.nodes USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_graphs_nodes_osm_id
ON graphs.nodes(osm_node_id) WHERE osm_node_id IS NOT NULL;

-- Edges table (road segments for routing)
CREATE TABLE IF NOT EXISTS graphs.edges (
    id SERIAL PRIMARY KEY,
    osm_way_id BIGINT,
    source BIGINT REFERENCES graphs.nodes(id),
    target BIGINT REFERENCES graphs.nodes(id),
    geom GEOMETRY(LineString, 4326) NOT NULL,
    
    -- Road attributes
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INT DEFAULT 1,
    oneway BOOLEAN DEFAULT false,
    
    -- Speed limits (km/h)
    maxspeed_kmh INT NOT NULL,
    
    -- Length (computed by trigger)
    length_m FLOAT NOT NULL,
    
    -- Capacity and load
    base_capacity INT NOT NULL,         -- max vehicles per hour
    current_load INT DEFAULT 0,         -- current number of agents
    
    -- Access restrictions
    access_type VARCHAR(50),            -- public, private, destination, no
    is_restricted BOOLEAN DEFAULT false,
    barrier_penalty_sec INT DEFAULT 0,  -- penalty for gates/barriers
    
    -- Dynamic fields (computed columns)
    effective_speed_kmh FLOAT GENERATED ALWAYS AS (
        CASE
            WHEN current_load = 0 THEN maxspeed_kmh::FLOAT
            WHEN current_load <= base_capacity THEN maxspeed_kmh::FLOAT
            ELSE GREATEST(5.0, maxspeed_kmh::FLOAT * (2.0 - current_load::FLOAT / base_capacity))
        END
    ) STORED,
    
    cost FLOAT GENERATED ALWAYS AS (
        length_m / (
            CASE
                WHEN current_load = 0 THEN maxspeed_kmh::FLOAT
                WHEN current_load <= base_capacity THEN maxspeed_kmh::FLOAT
                ELSE GREATEST(5.0, maxspeed_kmh::FLOAT * (2.0 - current_load::FLOAT / base_capacity))
            END / 3.6
        )
    ) STORED,
    
    reverse_cost FLOAT GENERATED ALWAYS AS (
        CASE
            WHEN oneway THEN -1.0
            ELSE length_m / (
                CASE
                    WHEN current_load = 0 THEN maxspeed_kmh::FLOAT
                    WHEN current_load <= base_capacity THEN maxspeed_kmh::FLOAT
                    ELSE GREATEST(5.0, maxspeed_kmh::FLOAT * (2.0 - current_load::FLOAT / base_capacity))
                END / 3.6
            )
        END
    ) STORED,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trigger to compute edge length from geometry
CREATE OR REPLACE FUNCTION graphs.compute_edge_length()
RETURNS TRIGGER AS $$
BEGIN
    -- Compute length in meters using Web Mercator projection
    NEW.length_m := ST_Length(ST_Transform(NEW.geom, 3857));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_length_trigger
BEFORE INSERT OR UPDATE OF geom ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION graphs.compute_edge_length();

-- Indexes for edges
CREATE INDEX IF NOT EXISTS idx_graphs_edges_source
ON graphs.edges(source);

CREATE INDEX IF NOT EXISTS idx_graphs_edges_target
ON graphs.edges(target);

CREATE INDEX IF NOT EXISTS idx_graphs_edges_geom
ON graphs.edges USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_graphs_edges_access
ON graphs.edges(access_type) WHERE access_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_graphs_edges_osm_way
ON graphs.edges(osm_way_id) WHERE osm_way_id IS NOT NULL;

-- Turn restrictions for pgRouting
CREATE TABLE IF NOT EXISTS graphs.turn_restrictions (
    id SERIAL PRIMARY KEY,
    from_edge BIGINT REFERENCES graphs.edges(id),
    to_edge BIGINT REFERENCES graphs.edges(id),
    via_node BIGINT REFERENCES graphs.nodes(id),
    restriction_type VARCHAR(50) NOT NULL,  -- no_left_turn, no_right_turn, etc.
    cost FLOAT DEFAULT 1000000.0,           -- High cost = prohibited
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from
ON graphs.turn_restrictions(from_edge);

CREATE INDEX IF NOT EXISTS idx_turn_restrictions_to
ON graphs.turn_restrictions(to_edge);

CREATE INDEX IF NOT EXISTS idx_turn_restrictions_via
ON graphs.turn_restrictions(via_node);

-- Comments for documentation
COMMENT ON SCHEMA graphs IS 'Routing graph schema for pgRouting';
COMMENT ON TABLE graphs.nodes IS 'Intersection points and road endpoints';
COMMENT ON TABLE graphs.edges IS 'Road segments with dynamic cost calculation';
COMMENT ON TABLE graphs.turn_restrictions IS 'Turn restrictions from OSM relations';
COMMENT ON COLUMN graphs.edges.cost IS 'Travel time in seconds (dynamic based on load)';
COMMENT ON COLUMN graphs.edges.reverse_cost IS 'Reverse cost (-1 for oneway streets)';
COMMENT ON COLUMN graphs.edges.effective_speed_kmh IS 'Effective speed considering traffic load';
