-- Migration: Update graphs schema for pgRouting compatibility
-- Date: 2025-11-27
-- Purpose: Add pgRouting-compatible columns and computed costs

-- Add missing columns to graphs.nodes
ALTER TABLE graphs.nodes
ADD COLUMN IF NOT EXISTS is_intersection BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS type VARCHAR(50) DEFAULT 'intersection',
ADD COLUMN IF NOT EXISTS has_barrier BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS barrier_type VARCHAR(50);

-- Add missing columns to graphs.edges
ALTER TABLE graphs.edges
ADD COLUMN IF NOT EXISTS access_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS is_restricted BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS barrier_penalty_sec INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS name VARCHAR(255);

-- Rename columns for pgRouting compatibility (if needed)
-- Note: We keep existing column names and add aliases via views if needed

-- Drop existing generated columns (will be recreated with new logic)
ALTER TABLE graphs.edges
DROP COLUMN IF EXISTS capacity CASCADE,
DROP COLUMN IF EXISTS base_travel_time_sec CASCADE,
DROP COLUMN IF EXISTS effective_speed_kmh CASCADE;

-- Add base_capacity column (replaces generated capacity)
ALTER TABLE graphs.edges
ADD COLUMN IF NOT EXISTS base_capacity INT NOT NULL DEFAULT 1000;

-- Update base_capacity based on lanes (for existing rows)
UPDATE graphs.edges
SET base_capacity = GREATEST(100, (length_m / 5.0)::INT * lanes)
WHERE base_capacity = 1000;

-- Add computed columns for pgRouting
ALTER TABLE graphs.edges
ADD COLUMN IF NOT EXISTS effective_speed_kmh FLOAT GENERATED ALWAYS AS (
    CASE
        WHEN current_load = 0 THEN speed_limit_kmh
        WHEN current_load <= base_capacity THEN speed_limit_kmh
        ELSE GREATEST(5.0, speed_limit_kmh * (2.0 - current_load::FLOAT / base_capacity))
    END
) STORED;

ALTER TABLE graphs.edges
ADD COLUMN IF NOT EXISTS cost FLOAT GENERATED ALWAYS AS (
    length_m / (
        CASE
            WHEN current_load = 0 THEN speed_limit_kmh
            WHEN current_load <= base_capacity THEN speed_limit_kmh
            ELSE GREATEST(5.0, speed_limit_kmh * (2.0 - current_load::FLOAT / base_capacity))
        END / 3.6
    )
) STORED;

ALTER TABLE graphs.edges
ADD COLUMN IF NOT EXISTS reverse_cost FLOAT GENERATED ALWAYS AS (
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
) STORED;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_graphs_edges_access_type
ON graphs.edges(access_type) WHERE access_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_graphs_edges_restricted
ON graphs.edges(is_restricted) WHERE is_restricted = true;

CREATE INDEX IF NOT EXISTS idx_graphs_nodes_barriers
ON graphs.nodes(has_barrier) WHERE has_barrier = true;

-- Create view for pgRouting compatibility (maps column names)
CREATE OR REPLACE VIEW graphs.edges_pgrouting AS
SELECT
    id,
    osm_way_id,
    start_node_id as source,
    end_node_id as target,
    geometry as geom,
    length_m,
    speed_limit_kmh as maxspeed_kmh,
    lanes,
    oneway,
    highway_type as highway,
    name,
    base_capacity,
    current_load,
    access_type,
    is_restricted,
    barrier_penalty_sec,
    effective_speed_kmh,
    cost,
    reverse_cost,
    created_at
FROM graphs.edges;

-- Update comments
COMMENT ON COLUMN graphs.edges.base_capacity IS 'Maximum vehicles per hour (static)';
COMMENT ON COLUMN graphs.edges.current_load IS 'Current number of agents on edge';
COMMENT ON COLUMN graphs.edges.effective_speed_kmh IS 'Effective speed considering traffic load';
COMMENT ON COLUMN graphs.edges.cost IS 'Travel time in seconds (dynamic based on load)';
COMMENT ON COLUMN graphs.edges.reverse_cost IS 'Reverse cost (-1 for oneway streets)';
COMMENT ON COLUMN graphs.edges.access_type IS 'Access restriction type (public, private, destination, no)';
COMMENT ON COLUMN graphs.edges.barrier_penalty_sec IS 'Time penalty for barriers in seconds';

COMMENT ON VIEW graphs.edges_pgrouting IS 'pgRouting-compatible view of edges table';
