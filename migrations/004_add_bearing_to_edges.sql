-- Migration 004: Add bearing column to edges table
-- Date: 2025-11-10
-- Purpose: Add bearing (azimuth) for turn cost calculations

-- Add bearing column as GENERATED (calculated from geometry)
ALTER TABLE edges 
ADD COLUMN IF NOT EXISTS bearing FLOAT 
GENERATED ALWAYS AS (
    CASE 
        WHEN ST_GeometryType(geometry) = 'ST_LineString' 
             AND ST_NumPoints(geometry) >= 2
        THEN degrees(ST_Azimuth(
            ST_StartPoint(geometry),
            ST_EndPoint(geometry)
        ))
        ELSE NULL
    END
) STORED;

-- Add index for bearing-based queries
CREATE INDEX IF NOT EXISTS idx_edges_bearing ON edges(bearing);

-- Update statistics
ANALYZE edges;

-- Verify
SELECT COUNT(*) as total_edges,
       COUNT(bearing) as edges_with_bearing,
       MIN(bearing) as min_bearing,
       MAX(bearing) as max_bearing,
       AVG(bearing) as avg_bearing
FROM edges;
