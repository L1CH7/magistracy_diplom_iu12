-- Migration 008: Add download tracking columns to cached_tiles
-- Purpose: Track tile download status, attempts, errors, and timestamps
-- Date: 2025-01-19

-- Add download status tracking
ALTER TABLE osm.cached_tiles
  ADD COLUMN IF NOT EXISTS download_status text DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS download_error text,
  ADD COLUMN IF NOT EXISTS download_attempts integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_download_attempt timestamp without time zone,
  ADD COLUMN IF NOT EXISTS downloaded_at timestamp without time zone;

-- Create index for download status queries
CREATE INDEX IF NOT EXISTS idx_cached_tiles_download_status 
ON osm.cached_tiles USING BTREE(download_status);

-- Create index for finding stuck downloads
CREATE INDEX IF NOT EXISTS idx_cached_tiles_last_download 
ON osm.cached_tiles USING BTREE(last_download_attempt)
WHERE download_status = 'downloading';

-- Comments
COMMENT ON COLUMN osm.cached_tiles.download_status IS 'Download status: pending, downloading, complete, failed';
COMMENT ON COLUMN osm.cached_tiles.download_error IS 'Error message if download failed';
COMMENT ON COLUMN osm.cached_tiles.download_attempts IS 'Number of download attempts';
COMMENT ON COLUMN osm.cached_tiles.last_download_attempt IS 'Timestamp of last download attempt';
COMMENT ON COLUMN osm.cached_tiles.downloaded_at IS 'Timestamp of successful download completion';
