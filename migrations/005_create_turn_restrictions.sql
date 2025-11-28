-- Migration 005: Create turn_restrictions table
-- Date: 2025-11-28
-- Purpose: Store turn restrictions for routing

CREATE TABLE graphs.turn_restrictions (
    id SERIAL PRIMARY KEY,
    from_edge INT NOT NULL REFERENCES graphs.edges(id),
    to_edge INT NOT NULL REFERENCES graphs.edges(id),
    via_node INT NOT NULL REFERENCES graphs.nodes(id),
    
    restriction_type VARCHAR(50) NOT NULL,
    -- Examples: 'no_left_turn', 'no_right_turn', 'no_u_turn', 'no_straight_on', 'only_right_turn'
    
    cost FLOAT DEFAULT 1000000.0,
    -- Large cost = prohibited, smaller cost = discouraged
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== INDEXES ====================
CREATE INDEX idx_turn_restrictions_from ON graphs.turn_restrictions(from_edge);
CREATE INDEX idx_turn_restrictions_to ON graphs.turn_restrictions(to_edge);
CREATE INDEX idx_turn_restrictions_via ON graphs.turn_restrictions(via_node);

-- ==================== COMMENTS ====================
COMMENT ON TABLE graphs.turn_restrictions IS 'OSM turn restrictions for routing';
COMMENT ON COLUMN graphs.turn_restrictions.restriction_type IS 'OSM restriction type (no_left_turn, etc.)';
COMMENT ON COLUMN graphs.turn_restrictions.cost IS 'pgRouting cost: 1000000 = prohibited, <1000 = discouraged';
