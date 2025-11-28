-- Migration 000: Enable PostGIS and pgRouting extensions
-- Date: 2025-11-28
-- Purpose: Enable spatial database extensions

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

-- Verify extensions
SELECT 
    extname, 
    extversion 
FROM pg_extension 
WHERE extname IN ('postgis', 'pgrouting');
