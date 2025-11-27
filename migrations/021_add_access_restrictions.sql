-- Migration 021: Add access restriction columns to osm.ways (without DROP)
-- Date: 2025-11-27
-- Fix: Previous migration 020 dropped osm.ways, losing geom_3857 column

-- ========================================
-- 1. Add new columns to osm.ways (if not exist)
-- ========================================

-- Oneway flag (extracted from tags)
ALTER TABLE osm.ways
ADD COLUMN IF NOT EXISTS oneway BOOLEAN DEFAULT false;

-- Access restrictions
ALTER TABLE osm.ways
ADD COLUMN IF NOT EXISTS access VARCHAR(50);

ALTER TABLE osm.ways
ADD COLUMN IF NOT EXISTS motor_vehicle VARCHAR(50);

ALTER TABLE osm.ways
ADD COLUMN IF NOT EXISTS service VARCHAR(50);

-- Create indexes for new columns
CREATE INDEX IF NOT EXISTS idx_osm_ways_access 
ON osm.ways(access) WHERE access IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_osm_ways_service 
ON osm.ways(service) WHERE service IS NOT NULL;

-- ========================================
-- 2. Create barriers table (idempotent)
-- ========================================

CREATE TABLE IF NOT EXISTS osm.barriers (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    geom GEOMETRY(Point, 4326) NOT NULL,
    
    -- Barrier type
    barrier_type VARCHAR(50) NOT NULL,
    
    -- Access control
    access VARCHAR(50),
    motor_vehicle VARCHAR(50),
    
    -- Metadata
    name VARCHAR(255),
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_osm_barriers_geom 
ON osm.barriers USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_osm_barriers_type 
ON osm.barriers(barrier_type);

CREATE INDEX IF NOT EXISTS idx_osm_barriers_access 
ON osm.barriers(access) WHERE access IS NOT NULL;

-- ========================================
-- 3. Create turn_restrictions table (idempotent)
-- ========================================

CREATE TABLE IF NOT EXISTS osm.turn_restrictions (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    
    -- Restriction type
    restriction_type VARCHAR(50) NOT NULL,
    
    -- Members (from relation)
    from_way BIGINT,
    via_node BIGINT,
    via_way BIGINT,
    to_way BIGINT,
    
    -- Metadata
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_restrictions_from 
ON osm.turn_restrictions(from_way);

CREATE INDEX IF NOT EXISTS idx_restrictions_via_node 
ON osm.turn_restrictions(via_node) WHERE via_node IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_restrictions_to 
ON osm.turn_restrictions(to_way);

CREATE INDEX IF NOT EXISTS idx_restrictions_type 
ON osm.turn_restrictions(restriction_type);

-- ========================================
-- 4. Comments
-- ========================================

COMMENT ON COLUMN osm.ways.access IS 
'Access restriction (private, no, destination, etc)';

COMMENT ON COLUMN osm.ways.motor_vehicle IS 
'Motor vehicle access (no = prohibited)';

COMMENT ON COLUMN osm.ways.service IS 
'Service type (driveway, parking_aisle, etc)';

COMMENT ON COLUMN osm.ways.oneway IS 
'One-way road flag (extracted from tags or inferred from highway type)';

COMMENT ON TABLE osm.barriers IS 
'Physical barriers (gates, bollards, etc)';

COMMENT ON COLUMN osm.barriers.barrier_type IS 
'Type: gate, boom, bollard, lift_gate, sliding_gate, block, etc';

COMMENT ON COLUMN osm.barriers.access IS 
'Access control: private, destination, public, no';

COMMENT ON TABLE osm.turn_restrictions IS 
'Turn restrictions from OSM relations';

COMMENT ON COLUMN osm.turn_restrictions.restriction_type IS 
'no_left_turn, no_right_turn, no_u_turn, only_straight_on, only_right_turn, etc';

COMMENT ON COLUMN osm.turn_restrictions.via_node IS 
'Intersection node (most common)';

COMMENT ON COLUMN osm.turn_restrictions.via_way IS 
'Via way segment (less common)';
