-- Migration 002: Create graphs schema and system config table
-- Date: 2025-11-28
-- Purpose: Create routing graph schema and configuration storage

CREATE SCHEMA IF NOT EXISTS graphs;
GRANT USAGE ON SCHEMA graphs TO diplom;
GRANT CREATE ON SCHEMA graphs TO diplom;

COMMENT ON SCHEMA graphs IS 'Routing graph derived from OSM data';

-- System configuration table
CREATE TABLE graphs.system_config (
    key_name TEXT PRIMARY KEY,
    value_numeric NUMERIC,
    value_text TEXT,
    description TEXT
);

-- Insert default values (will be updated by GraphBuilder from YAML)
INSERT INTO graphs.system_config (key_name, value_numeric, description) VALUES
    ('length_auto_m', 5.0, 'Average vehicle length in meters'),
    ('safe_distance_s', 3.0, 'Safe time distance between vehicles in seconds'),
    ('speed_tolerance_kmh', 19.0, 'Speed tolerance for RF (maxspeed + 19)'),
    ('min_speed_kmh', 5.0, 'Minimum speed in congestion (jam speed)');

COMMENT ON TABLE graphs.system_config IS 'Configuration parameters for graph calculations';
COMMENT ON COLUMN graphs.system_config.key_name IS 'Configuration key';
COMMENT ON COLUMN graphs.system_config.value_numeric IS 'Numeric value';
COMMENT ON COLUMN graphs.system_config.value_text IS 'Text value (for non-numeric configs)';
