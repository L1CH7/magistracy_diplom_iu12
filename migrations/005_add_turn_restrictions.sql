-- Migration 005: Add turn restrictions table
-- Stores OSM turn restrictions for routing

CREATE TABLE IF NOT EXISTS turn_restrictions (
    id SERIAL PRIMARY KEY,
    osm_relation_id BIGINT NOT NULL,
    restriction_type VARCHAR(50) NOT NULL,  -- e.g., no_left_turn, only_straight_on
    from_way_id BIGINT NOT NULL,  -- OSM way ID
    via_node_id BIGINT NOT NULL,  -- OSM node ID (intersection)
    to_way_id BIGINT NOT NULL,    -- OSM way ID
    is_prohibitive BOOLEAN NOT NULL DEFAULT FALSE,  -- True for "no_*"
    is_mandatory BOOLEAN NOT NULL DEFAULT FALSE,    -- True for "only_*"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(osm_relation_id)
);

-- Index for fast lookup during routing: (from_way, via_node)
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_lookup
ON turn_restrictions (from_way_id, via_node_id);

-- Index by restriction type
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_type
ON turn_restrictions (restriction_type);

-- Index by via node (for queries like "all restrictions at intersection X")
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_via_node
ON turn_restrictions (via_node_id);

COMMENT ON TABLE turn_restrictions IS 
'Turn restrictions from OSM relations (type=restriction). Used for routing to enforce turn rules.';

COMMENT ON COLUMN turn_restrictions.restriction_type IS 
'OSM restriction type: no_left_turn, no_right_turn, no_u_turn, only_straight_on, etc.';

COMMENT ON COLUMN turn_restrictions.from_way_id IS 
'OSM way ID that agent is coming from';

COMMENT ON COLUMN turn_restrictions.via_node_id IS 
'OSM node ID of intersection (via point)';

COMMENT ON COLUMN turn_restrictions.to_way_id IS 
'OSM way ID that restriction applies to';

COMMENT ON COLUMN turn_restrictions.is_prohibitive IS 
'True for prohibitive restrictions (no_*): turn is forbidden';

COMMENT ON COLUMN turn_restrictions.is_mandatory IS 
'True for mandatory restrictions (only_*): only this turn is allowed';
