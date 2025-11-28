-- Migration 008: OSM turn restrictions staging table
-- Description: Stores raw turn restrictions from OSM before processing into graphs.turn_restrictions
-- Dependencies: 001_init_osm_schema.sql (osm.ways)

-- OSM turn restrictions (raw data from Overpass API)
CREATE TABLE IF NOT EXISTS osm.turn_restrictions (
    id SERIAL PRIMARY KEY,
    osm_relation_id BIGINT UNIQUE NOT NULL,  -- OSM relation ID
    restriction_type VARCHAR(50) NOT NULL,    -- Type: no_left_turn, no_right_turn, only_straight_on, etc.
    
    -- Members of the relation
    from_way_id BIGINT NOT NULL,             -- Way you're coming from
    via_node_id BIGINT,                      -- Node where restriction applies (can be NULL if via is way)
    via_way_id BIGINT,                       -- Way where restriction applies (can be NULL if via is node)
    to_way_id BIGINT NOT NULL,               -- Way you're going to
    
    -- Metadata
    tags JSONB,                              -- Full OSM tags
    except_tags TEXT[],                      -- Exceptions (e.g., ['psv', 'bicycle'])
    
    -- Timing info
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from_way 
    ON osm.turn_restrictions(from_way_id);
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_via_node 
    ON osm.turn_restrictions(via_node_id) WHERE via_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_via_way 
    ON osm.turn_restrictions(via_way_id) WHERE via_way_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_to_way 
    ON osm.turn_restrictions(to_way_id);
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_type 
    ON osm.turn_restrictions(restriction_type);
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_osm_id 
    ON osm.turn_restrictions(osm_relation_id);

-- Update timestamp trigger
CREATE TRIGGER update_turn_restrictions_timestamp
    BEFORE UPDATE ON osm.turn_restrictions
    FOR EACH ROW
    EXECUTE FUNCTION osm.update_timestamp();

COMMENT ON TABLE osm.turn_restrictions IS 'Raw turn restrictions from OSM (staging before graph processing)';
COMMENT ON COLUMN osm.turn_restrictions.via_node_id IS 'Node-based restriction (most common)';
COMMENT ON COLUMN osm.turn_restrictions.via_way_id IS 'Way-based restriction (less common)';
COMMENT ON COLUMN osm.turn_restrictions.except_tags IS 'Vehicle types exempt from restriction';
