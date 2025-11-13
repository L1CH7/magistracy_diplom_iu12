-- Migration: Add geom_3857 column for efficient MVT rendering
-- Date: 2025-11-13
-- Purpose: Store pre-computed Web Mercator geometries to avoid 
--          real-time ST_Transform during tile generation

-- Add Web Mercator geometry column
ALTER TABLE osm.ways 
ADD COLUMN IF NOT EXISTS geom_3857 geometry(LineString, 3857);

-- Create GIST index for spatial queries
CREATE INDEX IF NOT EXISTS idx_osm_ways_geom_3857 
ON osm.ways USING GIST(geom_3857);

-- Create trigger function to auto-sync geom_3857 on INSERT/UPDATE
CREATE OR REPLACE FUNCTION osm.sync_geom_3857() 
RETURNS TRIGGER AS $$
BEGIN
    -- Transform from SRID 4326 to 3857 (Web Mercator)
    NEW.geom_3857 := ST_Transform(NEW.geom, 3857);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to auto-populate geom_3857
DROP TRIGGER IF EXISTS ways_sync_3857 ON osm.ways;
CREATE TRIGGER ways_sync_3857
BEFORE INSERT OR UPDATE ON osm.ways
FOR EACH ROW 
EXECUTE FUNCTION osm.sync_geom_3857();

-- Backfill existing rows (for production: do this in batches!)
-- UPDATE osm.ways SET geom_3857 = ST_Transform(geom, 3857) 
-- WHERE geom_3857 IS NULL;

-- For large tables, use batched update:
DO $$
DECLARE
    batch_size INT := 10000;
    updated INT;
    total INT;
BEGIN
    SELECT COUNT(*) INTO total 
    FROM osm.ways WHERE geom_3857 IS NULL;
    
    RAISE NOTICE 'Backfilling geom_3857 for % rows...', total;
    
    LOOP
        UPDATE osm.ways
        SET geom_3857 = ST_Transform(geom, 3857)
        WHERE osm_id IN (
            SELECT osm_id FROM osm.ways 
            WHERE geom_3857 IS NULL 
            LIMIT batch_size
        );
        
        GET DIAGNOSTICS updated = ROW_COUNT;
        EXIT WHEN updated = 0;
        
        RAISE NOTICE 'Updated % rows...', updated;
        COMMIT;
    END LOOP;
    
    RAISE NOTICE 'Backfill complete!';
END $$;

-- Verify migration
SELECT 
    COUNT(*) as total_ways,
    COUNT(geom_3857) as filled_3857,
    COUNT(*) - COUNT(geom_3857) as missing_3857
FROM osm.ways;
