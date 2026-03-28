CREATE TABLE IF NOT EXISTS osm.turn_restrictions (
    osm_id BIGINT PRIMARY KEY,
    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    members JSONB NOT NULL DEFAULT '[]'::jsonb
);

COMMENT ON TABLE osm.turn_restrictions IS 
'Raw OSM turn restrictions from relations (type=restriction).';

COMMENT ON COLUMN osm.turn_restrictions.osm_id IS 
'Original OSM relation ID';

COMMENT ON COLUMN osm.turn_restrictions.tags IS 
'Full OSM tags for the restriction relation';

COMMENT ON COLUMN osm.turn_restrictions.members IS 
'Full OSM members for the restriction relation (from, via, to)';
