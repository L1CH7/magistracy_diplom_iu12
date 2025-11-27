-- Migration: Add OSM data tables with barriers and restrictions
-- Date: 2025-11-26
-- Based on: routing_restrictions_and_osm_changes_architecture_plan.md

-- Create osm schema if not exists
CREATE SCHEMA IF NOT EXISTS osm;

-- ========================================
-- 1. OSM WAYS (roads)
-- ========================================

-- Drop old table if exists
DROP TABLE IF EXISTS osm.ways CASCADE;

CREATE TABLE osm.ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}',
    
    -- Core attributes (extracted from tags for indexing)
    highway VARCHAR(50),
    name VARCHAR(255),
    lanes INT,
    maxspeed VARCHAR(20),         -- Can be "60", "RU:urban", "none", etc
    oneway BOOLEAN DEFAULT false,
    
    -- Access restrictions
    access VARCHAR(50),            -- private, no, destination, permissive, etc
    motor_vehicle VARCHAR(50),     -- no (запрет авто)
    service VARCHAR(50),           -- driveway, parking_aisle, etc
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_osm_ways_geom ON osm.ways USING GIST(geom);
CREATE INDEX idx_osm_ways_highway ON osm.ways(highway) WHERE highway IS NOT NULL;
CREATE INDEX idx_osm_ways_access ON osm.ways(access) WHERE access IS NOT NULL;
CREATE INDEX idx_osm_ways_service ON osm.ways(service) WHERE service IS NOT NULL;
CREATE INDEX idx_osm_ways_tags ON osm.ways USING GIN(tags);

-- ========================================
-- 2. BARRIERS (gates, bollards, etc)
-- ========================================

DROP TABLE IF EXISTS osm.barriers CASCADE;

CREATE TABLE osm.barriers (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    geom GEOMETRY(Point, 4326) NOT NULL,
    
    -- Barrier type
    barrier_type VARCHAR(50) NOT NULL,    -- gate, boom, bollard, lift_gate, block, etc
    
    -- Access control
    access VARCHAR(50),                   -- private, destination, public, no
    motor_vehicle VARCHAR(50),            -- private, no
    
    -- Metadata
    name VARCHAR(255),
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_osm_barriers_geom ON osm.barriers USING GIST(geom);
CREATE INDEX idx_osm_barriers_type ON osm.barriers(barrier_type);
CREATE INDEX idx_osm_barriers_access ON osm.barriers(access) WHERE access IS NOT NULL;

-- ========================================
-- 3. TURN RESTRICTIONS (relations)
-- ========================================

DROP TABLE IF EXISTS osm.turn_restrictions CASCADE;

CREATE TABLE osm.turn_restrictions (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    
    -- Restriction type
    restriction_type VARCHAR(50) NOT NULL,  -- no_left_turn, no_right_turn, no_u_turn, 
                                             -- only_straight_on, only_right_turn, etc
    
    -- Members (from relation)
    from_way BIGINT,                        -- OSM way ID (start)
    via_node BIGINT,                        -- OSM node ID (intersection)
    via_way BIGINT,                         -- OSM way ID (via segment, optional)
    to_way BIGINT,                          -- OSM way ID (end)
    
    -- Metadata
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_restrictions_from ON osm.turn_restrictions(from_way);
CREATE INDEX idx_restrictions_via_node ON osm.turn_restrictions(via_node) WHERE via_node IS NOT NULL;
CREATE INDEX idx_restrictions_to ON osm.turn_restrictions(to_way);
CREATE INDEX idx_restrictions_type ON osm.turn_restrictions(restriction_type);

-- ========================================
-- 4. HELPER FUNCTIONS
-- ========================================

-- Extract boolean from tags
CREATE OR REPLACE FUNCTION osm.extract_oneway(tags JSONB, highway TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    -- Oneway tag
    IF tags->>'oneway' IN ('yes', '1', 'true') THEN
        RETURN true;
    END IF;
    
    -- Default oneway for motorway/trunk
    IF highway IN ('motorway', 'motorway_link', 'trunk_link') THEN
        RETURN true;
    END IF;
    
    RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Extract lanes count
CREATE OR REPLACE FUNCTION osm.extract_lanes(tags JSONB)
RETURNS INT AS $$
DECLARE
    lanes_str TEXT;
BEGIN
    lanes_str := tags->>'lanes';
    
    IF lanes_str IS NULL THEN
        RETURN 1;  -- Default
    END IF;
    
    -- Try to parse as integer
    BEGIN
        RETURN lanes_str::INT;
    EXCEPTION WHEN OTHERS THEN
        RETURN 1;
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Extract maxspeed (convert to integer km/h or NULL)
CREATE OR REPLACE FUNCTION osm.parse_maxspeed(maxspeed_str TEXT, highway TEXT, country TEXT DEFAULT 'RU')
RETURNS INT AS $$
BEGIN
    -- Try direct integer
    IF maxspeed_str ~ '^[0-9]+$' THEN
        RETURN maxspeed_str::INT;
    END IF;
    
    -- "RU:urban" = 60
    IF maxspeed_str = 'RU:urban' THEN
        RETURN 60;
    END IF;
    
    -- "RU:rural" = 90
    IF maxspeed_str = 'RU:rural' THEN
        RETURN 90;
    END IF;
    
    -- "RU:motorway" = 110
    IF maxspeed_str = 'RU:motorway' THEN
        RETURN 110;
    END IF;
    
    -- "none" or "signals" = NULL (will use default)
    IF maxspeed_str IN ('none', 'signals', 'variable') THEN
        RETURN NULL;
    END IF;
    
    -- Default by highway type (Russia)
    CASE highway
        WHEN 'motorway' THEN RETURN 110;
        WHEN 'trunk' THEN RETURN 90;
        WHEN 'primary' THEN RETURN 90;
        WHEN 'secondary' THEN RETURN 60;
        WHEN 'tertiary' THEN RETURN 60;
        WHEN 'residential' THEN RETURN 60;
        WHEN 'living_street' THEN RETURN 20;
        WHEN 'service' THEN RETURN 20;
        ELSE RETURN 50;
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ========================================
-- 5. COMMENTS
-- ========================================

COMMENT ON TABLE osm.ways IS 'OSM ways (roads) with extracted attributes';
COMMENT ON TABLE osm.barriers IS 'Physical barriers (gates, bollards, etc)';
COMMENT ON TABLE osm.turn_restrictions IS 'Turn restrictions from OSM relations';

COMMENT ON COLUMN osm.ways.access IS 'Access restriction (private, no, destination, etc)';
COMMENT ON COLUMN osm.ways.motor_vehicle IS 'Motor vehicle access (no = prohibited)';
COMMENT ON COLUMN osm.ways.service IS 'Service type (driveway, parking_aisle, etc)';

COMMENT ON COLUMN osm.barriers.barrier_type IS 'Type: gate, boom, bollard, lift_gate, sliding_gate, block, etc';
COMMENT ON COLUMN osm.barriers.access IS 'Access control: private, destination, public, no';

COMMENT ON COLUMN osm.turn_restrictions.restriction_type IS 'no_left_turn, no_right_turn, no_u_turn, only_straight_on, only_right_turn, etc';
COMMENT ON COLUMN osm.turn_restrictions.via_node IS 'Intersection node (most common)';
COMMENT ON COLUMN osm.turn_restrictions.via_way IS 'Via way segment (less common)';
