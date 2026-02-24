-- Migration 014: Fix download_status and download_error column types
-- Change from varchar to text to avoid asyncpg type inference issues

BEGIN;

-- Change download_status from varchar(20) to text
ALTER TABLE osm.cached_tiles
  ALTER COLUMN download_status TYPE text;

-- Change download_error from text to text (already text, but ensure)
ALTER TABLE osm.cached_tiles
  ALTER COLUMN download_error TYPE text;

COMMIT;
