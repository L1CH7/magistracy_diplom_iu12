-- Migration 009: Add routing-related columns to osm.ways
-- Purpose: Add columns for access control and routing rules
-- Date: 2025-01-19

-- Add routing-related columns
ALTER TABLE osm.ways
  ADD COLUMN IF NOT EXISTS oneway text,
  ADD COLUMN IF NOT EXISTS access text,
  ADD COLUMN IF NOT EXISTS motor_vehicle text,
  ADD COLUMN IF NOT EXISTS service text;

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_osm_ways_oneway 
ON osm.ways USING BTREE(oneway)
WHERE oneway IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_osm_ways_access 
ON osm.ways USING BTREE(access)
WHERE access IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_osm_ways_motor_vehicle 
ON osm.ways USING BTREE(motor_vehicle)
WHERE motor_vehicle IS NOT NULL;

-- Comments
COMMENT ON COLUMN osm.ways.oneway IS 'OSM oneway tag: yes/no/-1 (reverse direction)';
COMMENT ON COLUMN osm.ways.access IS 'OSM access tag: yes/no/private/permissive/etc';
COMMENT ON COLUMN osm.ways.motor_vehicle IS 'OSM motor_vehicle tag: yes/no/private/destination';
COMMENT ON COLUMN osm.ways.service IS 'OSM service tag: parking_aisle/driveway/alley/emergency_access';
