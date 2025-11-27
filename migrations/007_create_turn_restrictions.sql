-- Migration: Add turn restrictions table to graphs schema
-- Date: 2025-11-27
-- Purpose: Store turn restrictions for routing

CREATE TABLE IF NOT EXISTS graphs.turn_restrictions (
    id SERIAL PRIMARY KEY,
    from_edge INT REFERENCES graphs.edges(id),
    to_edge INT REFERENCES graphs.edges(id),
    via_node INT REFERENCES graphs.nodes(id),
    restriction_type VARCHAR(50) NOT NULL,
    cost FLOAT DEFAULT 1000000.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_turn_restrictions_from ON graphs.turn_restrictions(from_edge);
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_to ON graphs.turn_restrictions(to_edge);
CREATE INDEX IF NOT EXISTS idx_turn_restrictions_via ON graphs.turn_restrictions(via_node);

COMMENT ON TABLE graphs.turn_restrictions IS 'Turn restrictions from OSM relations';
COMMENT ON COLUMN graphs.turn_restrictions.restriction_type IS 'no_left_turn, no_right_turn, no_u_turn, only_straight_on, etc.';
COMMENT ON COLUMN graphs.turn_restrictions.cost IS 'High cost = prohibited (1000000.0), low cost = mandatory (0.1)';
