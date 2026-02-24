-- Migration: Add download status tracking to cached_tiles
-- Purpose: Track failed downloads to allow retry without clearing DB

-- Add columns for download status tracking
ALTER TABLE osm.cached_tiles 
  ADD COLUMN IF NOT EXISTS download_status VARCHAR(20) DEFAULT 'complete',
  ADD COLUMN IF NOT EXISTS download_error TEXT,
  ADD COLUMN IF NOT EXISTS download_attempts INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_download_attempt TIMESTAMP,
  ADD COLUMN IF NOT EXISTS downloaded_at TIMESTAMP;

-- Status values:
-- 'complete' - successfully downloaded, has data
-- 'failed' - download failed after all retries
-- 'empty' - successfully downloaded but no roads in this area
-- 'partial' - partial download (some data saved before error)

-- Add index for querying failed tiles
CREATE INDEX IF NOT EXISTS idx_cached_tiles_download_status 
  ON osm.cached_tiles(download_status);

-- Add comment
COMMENT ON COLUMN osm.cached_tiles.download_status IS 'Download status: complete, failed, empty, partial';
COMMENT ON COLUMN osm.cached_tiles.download_error IS 'Last error message if download failed';
COMMENT ON COLUMN osm.cached_tiles.download_attempts IS 'Number of download attempts';
COMMENT ON COLUMN osm.cached_tiles.last_download_attempt IS 'Timestamp of last download attempt';
COMMENT ON COLUMN osm.cached_tiles.downloaded_at IS 'Timestamp when successfully downloaded';
