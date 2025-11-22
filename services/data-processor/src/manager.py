"""
Data Processor Manager - OSM fetching and graph building.

Steps:
1. Fetch OSM data (Overpass API)
2. Parse OSM JSON
3. Build graph (nodes, edges)
4. Calculate bearings (ST_Azimuth)
5. Calculate capacity
6. Pre-compute geom_3857
7. Create indexes
"""

import uuid
import asyncpg
import asyncio
import time
import json
import os
import yaml
from pathlib import Path
from loguru import logger
from typing import Dict, List


class DataProcessorManager:
    """
    Process OSM data into navigation graph.
    
    Design:
    - Tile-based architecture (0.5°x0.5° OSM tiles)
    - Check tile existence in DB before download
    - On-demand download with progress tracking
    - PostgreSQL + PostGIS for storage
    """
    
    def __init__(self):
        # Database connection
        self.db_pool: asyncpg.Pool = None
        
        # Job registry (legacy)
        self.jobs: Dict[str, Dict] = {}
        
        # Tile download tracking
        self.downloading_tiles: Dict[tuple, Dict] = {}
        
        # In-memory cache: processed tiles (complete/empty/failed)
        # Format: {(lon, lat): {"status": str, "timestamp": float}}
        self.processed_tiles_cache: Dict[tuple, Dict] = {}
        
        # WebSocket notification callback (set by main.py)
        self.ws_notify_callback = None
        
        # Config from environment (infrastructure only)
        self.db_host = os.getenv("POSTGRES_HOST", "localhost")
        self.db_port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.db_name = os.getenv("POSTGRES_DB", "osm")
        self.db_user = os.getenv("POSTGRES_USER", "postgres")
        self.db_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        
        # Load business logic from configs
        self.tile_size_degrees = self._load_tile_size()
        self.default_bbox = self._load_default_bbox()
        self.overpass_config = self._load_overpass_config()
        
        logger.info("DataProcessorManager initialized (tile-based)")
    
    def set_ws_notify_callback(self, callback):
        """Set WebSocket notification callback."""
        self.ws_notify_callback = callback
        logger.info("WebSocket notification callback registered")
    
    def _load_tile_size(self) -> float:
        """
        Load tile_size_degrees from configs/data-processor/overpass.yaml.
        
        Returns:
            None - use monolithic mode (single tile for entire default bbox)
            float - use tiled mode with specified tile size
        """
        try:
            config_path = Path("/app/configs/data-processor/overpass.yaml")
            if not config_path.exists():
                config_path = (
                    Path(__file__).parent.parent.parent.parent
                    / "configs" / "data-processor" / "overpass.yaml"
                )
            
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                # Check if tile_size_degrees exists and is not None/null
                tile_size = config.get("tile_size_degrees")
                
                if tile_size is None:
                    logger.info(
                        "tile_size_degrees not set - using MONOLITHIC mode "
                        "(single tile for entire bbox)"
                    )
                    return None
                
                logger.info(
                    f"Loaded tile_size_degrees: {tile_size}° "
                    f"(~{tile_size * 111:.1f}km) - TILED mode"
                )
                return float(tile_size)
        except Exception as e:
            logger.error(
                f"Failed to load tile_size from config: {e}, "
                f"using MONOLITHIC mode"
            )
        
        return None
    
    def _load_default_bbox(self) -> Dict:
        """
        Load default bbox from configs/data-processor/bboxes.yaml.
        
        Returns bbox dict: {"west": float, "south": float, "east": float, "north": float}
        """
        import yaml
        from pathlib import Path
        
        try:
            # Try Docker path first, then local dev path
            config_path = Path("/app/configs/data-processor/bboxes.yaml")
            if not config_path.exists():
                config_path = (
                    Path(__file__).parent.parent.parent.parent
                    / "configs" / "data-processor" / "bboxes.yaml"
                )
            
            if not config_path.exists():
                logger.warning(f"Config not found, using fallback bounds")
                return {"west": 37.50, "south": 55.70, "east": 37.75, "north": 55.95}
            
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            default_bbox = config.get("default")
            if not default_bbox:
                logger.warning("No default bbox in config, using fallback")
                return {"west": 37.50, "south": 55.70, "east": 37.75, "north": 55.95}
            
            bbox_config = config.get(default_bbox)
            if not bbox_config:
                logger.warning(f"Bbox '{default_bbox}' not found, using fallback")
                return {"west": 37.50, "south": 55.70, "east": 37.75, "north": 55.95}
            
            coords = bbox_config.get("coords")
            if not coords or len(coords) != 4:
                logger.warning(f"Invalid coords in '{default_bbox}', using fallback")
                return {"west": 37.50, "south": 55.70, "east": 37.75, "north": 55.95}
            
            bbox = {
                "west": coords[0],
                "south": coords[1],
                "east": coords[2],
                "north": coords[3]
            }
            
            logger.info(
                f"Loaded default bbox '{default_bbox}': "
                f"[{bbox['west']}, {bbox['south']}, {bbox['east']}, {bbox['north']}]"
            )
            return bbox
            
        except Exception as e:
            logger.error(f"Failed to load bbox from config: {e}, using fallback")
            return {"west": 37.50, "south": 55.70, "east": 37.75, "north": 55.95}
    
    def _load_overpass_config(self) -> Dict:
        """
        Load Overpass configuration from configs/data-processor/overpass.yaml.
        
        Returns dict with retry settings, server lists, etc.
        """
        import yaml
        from pathlib import Path
        
        try:
            config_path = Path("/app/configs/data-processor/overpass.yaml")
            if not config_path.exists():
                config_path = (
                    Path(__file__).parent.parent.parent.parent
                    / "configs" / "data-processor" / "overpass.yaml"
                )
            
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                logger.info(
                    f"Loaded Overpass config: "
                    f"{len(config.get('primary_servers', []))} primary, "
                    f"{len(config.get('fallback_servers', []))} fallback servers"
                )
                return config
            else:
                logger.warning("Overpass config not found, using defaults")
                return self._get_default_overpass_config()
        
        except Exception as e:
            logger.error(f"Failed to load Overpass config: {e}, using defaults")
            return self._get_default_overpass_config()
    
    def _get_default_overpass_config(self) -> Dict:
        """Get default Overpass configuration if file not found."""
        return {
            "retry": {
                "max_retries_per_server": 3,
                "initial_retry_delay": 5,
                "max_retry_delay": 60,
                "backoff_multiplier": 2,
                "max_servers_to_try": 5
            },
            "primary_servers": [
                "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                "https://overpass.openstreetmap.ru/api/interpreter"
            ],
            "fallback_servers": [
                "https://overpass-api.de/api/interpreter",
                "https://overpass.kumi.systems/api/interpreter"
            ],
            "timeout": 300
        }
    
    async def initialize(self):
        """Initialize manager with connection retries."""
        max_retries = 10
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                self.db_pool = await asyncpg.create_pool(
                    host=self.db_host,
                    port=self.db_port,
                    database=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                    min_size=5,
                    max_size=20,
                    timeout=10
                )
                
                # Preload processed tiles cache from DB
                await self._preload_tiles_cache()
                
                logger.success("Data Processor initialized")
                return
            except Exception as e:
                logger.warning(
                    f"DB connection attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    raise
    
    async def _preload_tiles_cache(self):
        """
        Preload processed tiles cache from DB.
        
        Loads all tiles from cached_tiles table into memory cache
        to avoid DB queries spam on MVT requests.
        """
        import time
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT tile_key, download_status
                FROM osm.cached_tiles
                WHERE download_status IN ('complete', 'empty', 'partial', 'failed')
            """)
            
            for row in rows:
                # Parse tile_key "37.60_55.75" -> (37.60, 55.75)
                parts = row["tile_key"].split("_")
                if len(parts) == 2:
                    try:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        tile_key = (lon, lat)
                        
                        self.processed_tiles_cache[tile_key] = {
                            "status": row["download_status"],
                            "timestamp": time.time()
                        }
                    except ValueError:
                        continue
        
        logger.info(
            f"Preloaded {len(self.processed_tiles_cache)} tiles into memory cache"
        )
    
    async def shutdown(self):
        """Shutdown manager."""
        if self.db_pool:
            await self.db_pool.close()
        
        logger.info("Data Processor shutdown complete")
    
    def _coord_to_tile_key(self, lon: float, lat: float) -> tuple:
        """
        Convert coordinate to tile key.
        
        MONOLITHIC mode: returns (west, south) of default bbox
        TILED mode: returns (tile_lon, tile_lat) - bottom-left corner of tile
        
        Returns:
            (tile_lon, tile_lat) - bottom-left corner of tile
        """
        if self.tile_size_degrees is None:
            # MONOLITHIC mode - use entire default bbox as single tile
            return (self.default_bbox["west"], self.default_bbox["south"])
        
        # TILED mode - calculate tile grid coordinates
        tile_lon = (lon // self.tile_size_degrees) * self.tile_size_degrees
        tile_lat = (lat // self.tile_size_degrees) * self.tile_size_degrees
        return (tile_lon, tile_lat)
    
    def _tile_key_to_str(self, tile_key: tuple) -> str:
        """
        Convert tile_key to string for DB storage.
        
        MONOLITHIC mode: "monolith"
        TILED mode: "37.60_55.75"
        """
        if self.tile_size_degrees is None:
            return "monolith"
        return f"{tile_key[0]:.2f}_{tile_key[1]:.2f}"
    
    def _tile_to_bbox(self, tile_key: tuple) -> List[float]:
        """
        Convert tile key to bbox.
        
        MONOLITHIC mode: returns entire default bbox
        TILED mode: returns tile bbox
        """
        tile_lon, tile_lat = tile_key
        
        if self.tile_size_degrees is None:
            # MONOLITHIC mode - return entire default bbox
            return [
                self.default_bbox["west"],
                self.default_bbox["south"],
                self.default_bbox["east"],
                self.default_bbox["north"]
            ]
        
        # TILED mode - return tile bbox
        return [
            tile_lon,
            tile_lat,
            tile_lon + self.tile_size_degrees,
            tile_lat + self.tile_size_degrees
        ]
    
    async def check_tile_in_db(self, tile_key: tuple) -> Dict:
        """
        Check tile presence in database.
        
        CRITICAL: Check in-memory cache first to avoid DB queries spam.
        
        Returns:
            {"exists": bool, "ways_count": int, "status": str}
        """
        import time
        
        # Check in-memory cache FIRST (avoid DB spam)
        if tile_key in self.processed_tiles_cache:
            cached_entry = self.processed_tiles_cache[tile_key]
            age = time.time() - cached_entry["timestamp"]
            
            # Cache valid for 60 seconds
            if age < 60:
                status = cached_entry["status"]
                logger.debug(
                    f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                    f"found in memory cache: status={status}"
                )
                
                # If complete/empty/partial - tile exists
                if status in ("complete", "empty", "partial"):
                    return {"exists": True, "ways_count": 0, "status": status}
                
                # If failed >= 5 attempts - don't retry
                if status == "failed":
                    return {"exists": True, "ways_count": 0, "status": "failed"}
        
        tile_bbox = self._tile_to_bbox(tile_key)
        
        async with self.db_pool.acquire() as conn:
            # Check cached_tiles in DB
            # tile_key format: "37.60_55.75" or "monolith"
            cached = await conn.fetchrow("""
                SELECT download_status, download_attempts
                FROM osm.cached_tiles
                WHERE tile_key = $1
            """, self._tile_key_to_str(tile_key))
            
            if cached:
                status = cached["download_status"]
                
                # Count ways for this tile (if needed)
                ways_count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM osm.ways
                    WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
                """, tile_bbox[0], tile_bbox[1], tile_bbox[2], tile_bbox[3])
                
                # Tile already processed (complete/empty/partial)
                if status in ("complete", "empty", "partial"):
                    logger.debug(
                        f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                        f"already in cached_tiles: status={status}, ways={ways_count}"
                    )
                    return {"exists": True, "ways_count": ways_count, "status": status}
                
                # Failed tile - allow retry if attempts < 5
                if status == "failed":
                    attempts = cached["download_attempts"] or 0
                    if attempts >= 5:
                        logger.debug(
                            f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                            f"failed {attempts} times, not retrying"
                        )
                        return {"exists": True, "ways_count": 0, "status": "failed"}
                    else:
                        logger.debug(
                            f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                            f"failed {attempts} times, allowing retry"
                        )
                        return {"exists": False, "ways_count": 0, "status": "failed"}
            
            # Not in cached_tiles - check ways table (legacy)
            count = await conn.fetchval("""
                SELECT COUNT(*)
                FROM osm.ways
                WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
            """, tile_bbox[0], tile_bbox[1], tile_bbox[2], tile_bbox[3])
            
            exists = count > 0
            
            if exists:
                logger.debug(
                    f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                    f"exists in ways (legacy): {count} ways"
                )
            else:
                logger.debug(
                    f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                    f"missing from DB completely"
                )
            
            return {"exists": exists, "ways_count": count, "status": "ready"}
    
    async def get_global_status(self) -> Dict:
        """Get global Data Processor status."""
        # Count total tiles in DB
        async with self.db_pool.acquire() as conn:
            total_ways = await conn.fetchval(
                "SELECT COUNT(*) FROM osm.ways"
            )
        
        return {
            "active_downloads": len(self.downloading_tiles),
            "total_ways_in_db": total_ways,
            "downloading_tiles": [
                {"lon": k[0], "lat": k[1]}
                for k in self.downloading_tiles.keys()
            ]
        }
    
    async def ensure_tile_downloaded(self, tile_key: tuple) -> Dict:
        """
        Ensure tile is present in database with retry logic and fallback servers.
        
        If tile exists - return status.
        If downloading - return downloading status.
        If not - start download with retry/fallback, return downloading status.
        
        Returns:
            {"status": "exists|downloading|downloaded|failed", "ways_count": int}
        """
        import asyncio
        
        # Check if already downloading
        if tile_key in self.downloading_tiles:
            return {
                "status": "downloading",
                "ways_count": 0
            }
        
        # Check presence in DB
        check = await self.check_tile_in_db(tile_key)
        
        if check["exists"]:
            logger.info(
                f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                f"already in DB: {check['ways_count']} ways"
            )
            return {
                "status": "exists",
                "ways_count": check["ways_count"]
            }
        
        # Download tile with retry logic
        logger.info(
            f"Downloading tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}]"
        )
        
        # Mark as downloading
        self.downloading_tiles[tile_key] = {
            "status": "downloading",
            "progress": 0.0
        }
        
        # Load retry config
        retry_config = self.overpass_config.get("retry", {})
        max_retries_per_server = retry_config.get("max_retries_per_server", 3)
        initial_delay = retry_config.get("initial_retry_delay", 5)
        max_delay = retry_config.get("max_retry_delay", 60)
        backoff_multiplier = retry_config.get("backoff_multiplier", 2)
        max_servers = retry_config.get("max_servers_to_try", 5)
        
        # Build server list (primary + fallback)
        primary = self.overpass_config.get("primary_servers", [])
        fallback = self.overpass_config.get("fallback_servers", [])
        all_servers = (primary + fallback)[:max_servers]
        
        if not all_servers:
            logger.error("No Overpass servers configured!")
            if tile_key in self.downloading_tiles:
                del self.downloading_tiles[tile_key]
            return {"status": "failed", "error": "No servers configured"}
        
        from src.data.osm_overpass import build_highway_query
        
        tile_bbox = self._tile_to_bbox(tile_key)
        query = build_highway_query(
            (tile_bbox[1], tile_bbox[0], tile_bbox[3], tile_bbox[2])
        )
        
        total_attempts = 0
        last_error = None
        
        # Try each server
        for server_idx, server_url in enumerate(all_servers):
            logger.info(
                f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                f"trying server {server_idx + 1}/{len(all_servers)}: {server_url}"
            )
            
            # Retry loop for current server
            delay = initial_delay
            for retry in range(max_retries_per_server):
                total_attempts += 1
                
                try:
                    from src.data.osm_overpass import fetch_overpass_from_url
                    import time
                    
                    # Log download start for user feedback
                    start_time = time.time()
                    logger.info(
                        f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                        f"downloading from {server_url}..."
                    )
                    
                    # Fetch tile from specific server
                    osm_data = await fetch_overpass_from_url(
                        server_url, query, timeout=self.overpass_config.get("timeout", 300)
                    )
                    
                    # Success! Log download time
                    download_time = time.time() - start_time
                    elements = osm_data.get("elements", [])
                    ways = [e for e in elements if e.get("type") == "way"]
                    ways_count = len(ways)
                    
                    logger.info(
                        f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                        f"fetched: {ways_count} ways in {download_time:.1f}s (attempt {total_attempts})"
                    )
                    
                    saved_count = await self._save_ways_to_db(osm_data, tile_key)
                    
                    # Remove from downloading
                    del self.downloading_tiles[tile_key]
                    
                    # Add to memory cache
                    import time
                    self.processed_tiles_cache[tile_key] = {
                        "status": "complete" if saved_count > 0 else "empty",
                        "timestamp": time.time()
                    }
                    
                    logger.success(
                        f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                        f"saved: {saved_count} ways (server: {server_url})"
                    )
                    
                    # Notify WebSocket clients
                    await self._notify_tile_ready(tile_key)
                    
                    return {
                        "status": "downloaded",
                        "ways_count": saved_count
                    }
                    
                except Exception as e:
                    # Capture full error details
                    error_msg = str(e) if str(e) else repr(e)
                    error_type = type(e).__name__
                    last_error = f"{error_type}: {error_msg}"
                    
                    logger.warning(
                        f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                        f"attempt {total_attempts} failed: {last_error}"
                    )
                    
                    # Wait before retry (exponential backoff)
                    if retry < max_retries_per_server - 1:
                        logger.info(f"Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_multiplier, max_delay)
            
            # All retries for this server failed, try next server
            logger.warning(
                f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                f"all retries failed for server {server_url}"
            )
        
        # All servers exhausted
        logger.error(
            f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
            f"download FAILED after {total_attempts} attempts across {len(all_servers)} servers. "
            f"Last error: {last_error}"
        )
        
        # Mark as failed in DB
        await self._mark_tile_failed(tile_key, last_error, total_attempts)
        
        # Remove from downloading
        if tile_key in self.downloading_tiles:
            del self.downloading_tiles[tile_key]
        
        # Add to memory cache (prevent retry for 60s)
        import time
        self.processed_tiles_cache[tile_key] = {
            "status": "failed",
            "timestamp": time.time()
        }
        
        return {
            "status": "failed",
            "error": last_error,
            "attempts": total_attempts
        }
    
    async def start_fetch_job(
        self,
        bbox: List[float],
        highway_types: List[str]
    ) -> str:
        """Start OSM data fetch job."""
        job_id = str(uuid.uuid4())
        
        self.jobs[job_id] = {
            "type": "fetch",
            "status": "started",
            "bbox": bbox,
            "highway_types": highway_types,
            "progress": 0.0
        }
        
        logger.info(f"Fetch job started: {job_id}")
        
        return job_id
    
    def _split_bbox_into_tiles(
        self, 
        bbox: List[float], 
        grid_size: int = 4
    ) -> List[List[float]]:
        """
        Split bbox into tiles for progressive loading.
        
        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]
            grid_size: grid size (4 = 4x4 = 16 tiles)
        
        Returns:
            List of tile bboxes
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        
        lon_step = (max_lon - min_lon) / grid_size
        lat_step = (max_lat - min_lat) / grid_size
        
        tiles = []
        for i in range(grid_size):
            for j in range(grid_size):
                tile_bbox = [
                    min_lon + j * lon_step,
                    min_lat + i * lat_step,
                    min_lon + (j + 1) * lon_step,
                    min_lat + (i + 1) * lat_step
                ]
                tiles.append(tile_bbox)
        
        return tiles
    
    async def run_fetch_job(self, job_id: str):
        """
        Run fetch job (background) with progressive tile downloading.
        
        Splits bbox into tiles and downloads them progressively.
        """
        from src.data.osm_overpass import fetch_overpass, build_highway_query
        
        logger.info(f"Running fetch job: {job_id}")
        
        self.jobs[job_id]["status"] = "running"
        
        try:
            job_data = self.jobs[job_id]
            bbox = job_data["bbox"]  # [min_lon, min_lat, max_lon, max_lat]
            highway_types = job_data.get("highway_types", [])
            
            # Split bbox into tiles (4x4 = 16 tiles)
            tiles = self._split_bbox_into_tiles(bbox, grid_size=4)
            total_tiles = len(tiles)
            
            logger.info(
                f"Bbox {bbox} split into {total_tiles} tiles",
                bbox=bbox,
                total_tiles=total_tiles
            )
            
            total_ways = 0
            
            # Download each tile
            for tile_idx, tile_bbox in enumerate(tiles, start=1):
                logger.info(
                    f"Downloading tile {tile_idx}/{total_tiles}",
                    tile=tile_idx,
                    total=total_tiles,
                    bbox=tile_bbox
                )
                
                # Build Overpass query (south, west, north, east)
                query = build_highway_query(
                    (tile_bbox[1], tile_bbox[0], tile_bbox[3], tile_bbox[2])
                )
                
                # Fetch tile from Overpass API
                osm_data = fetch_overpass(query, timeout=60)
                
                # Count elements
                elements = osm_data.get("elements", [])
                ways = [e for e in elements if e.get("type") == "way"]
                ways_count = len(ways)
                
                logger.debug(
                    f"Tile {tile_idx}/{total_tiles}: {ways_count} ways",
                    tile=tile_idx,
                    ways=ways_count
                )
                
                # Save to PostgreSQL osm.ways table
                saved_count = await self._save_ways_to_db(osm_data)
                total_ways += saved_count
                
                # Update progress
                progress = tile_idx / total_tiles
                self.jobs[job_id]["progress"] = progress
                self.jobs[job_id]["tiles_done"] = tile_idx
                self.jobs[job_id]["tiles_total"] = total_tiles
                self.jobs[job_id]["ways_count"] = total_ways
                
                logger.info(
                    f"Progress: {tile_idx}/{total_tiles} tiles "
                    f"({progress*100:.1f}%), total {total_ways} ways"
                )
                
                # Small delay between tiles to avoid Overpass rate limiting
                await asyncio.sleep(0.5)
            
            self.jobs[job_id]["status"] = "done"
            self.jobs[job_id]["progress"] = 1.0
            
            logger.success(
                f"Fetch job complete: {job_id}, "
                f"loaded {total_ways} ways"
            )
            
        except Exception as e:
            logger.error(f"Fetch job failed: {str(e)}", exc_info=True)
            self.jobs[job_id]["status"] = "error"
            self.jobs[job_id]["error"] = str(e)
    
    async def _save_ways_to_db(
        self,
        osm_data: dict,
        tile_key: tuple = None
    ) -> int:
        """
        Save OSM ways to PostgreSQL osm.ways table.
        
        Args:
            osm_data: OSM JSON data
            tile_key: Optional tile key for progress logging
        
        Returns:
            Number of ways saved
        """
        elements = osm_data.get("elements", [])
        ways = [e for e in elements if e.get("type") == "way"]
        
        if not ways:
            return 0
        
        total_ways = len(ways)
        logger.info(f"Saving {total_ways} ways to osm.ways")
        
        saved_count = 0
        log_interval = max(1, total_ways // 10)  # Log every 10%
        way_data = []  # Batch data for COPY
        
        async with self.db_pool.acquire() as conn:
            for idx, way in enumerate(ways, start=1):
                osm_id = way.get("id")
                tags = way.get("tags", {})
                highway = tags.get("highway")
                
                if not highway:
                    continue
                
                # Filter: only drivable roads
                drivable_types = {
                    'motorway', 'motorway_link',
                    'trunk', 'trunk_link',
                    'primary', 'primary_link',
                    'secondary', 'secondary_link',
                    'tertiary', 'tertiary_link',
                    'unclassified', 'residential',
                    'living_street', 'service'
                }
                
                if highway not in drivable_types:
                    continue
                
                # Build LineString from nodes
                nodes = way.get("nodes", [])
                if len(nodes) < 2:
                    continue
                
                # Get node coordinates
                node_coords = []
                for node_id in nodes:
                    node = next(
                        (e for e in elements 
                         if e.get("type") == "node" and e.get("id") == node_id),
                        None
                    )
                    if node:
                        lon = node.get("lon")
                        lat = node.get("lat")
                        if lon is not None and lat is not None:
                            node_coords.append([lon, lat])
                
                if len(node_coords) < 2:
                    continue
                
                # Build geometry as LineString
                geom_json = {
                    "type": "LineString",
                    "coordinates": node_coords
                }
                
                # Collect data for batch insert
                way_data.append((
                    osm_id,
                    json.dumps(geom_json),
                    json.dumps(tags),
                    highway,
                    tags.get("name"),
                    (int(tags.get("lanes"))
                     if tags.get("lanes") and tags.get("lanes").isdigit()
                     else None),
                    tags.get("maxspeed")
                ))
                
                saved_count += 1
                
                # Log progress every 10%
                if idx % log_interval == 0 or idx == total_ways:
                    progress_pct = (idx / total_ways) * 100
                    if tile_key:
                        logger.info(
                            f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                            f"saving: {idx}/{total_ways} ways "
                            f"({progress_pct:.0f}%)"
                        )
                    else:
                        logger.info(
                            f"Saving: {idx}/{total_ways} ways "
                            f"({progress_pct:.0f}%)"
                        )
            
            # Batch insert via executemany
            if way_data:
                start_time = time.time()
                await conn.executemany(
                    """
                    INSERT INTO osm.ways (
                        osm_id, geom, geom_3857, tags, highway, name,
                        lanes, maxspeed
                    ) VALUES (
                        $1,
                        ST_GeomFromGeoJSON($2),
                        ST_Transform(ST_GeomFromGeoJSON($2), 3857),
                        $3::jsonb,
                        $4, $5, $6::integer, $7
                    )
                    ON CONFLICT (osm_id) DO UPDATE
                    SET geom = EXCLUDED.geom,
                        geom_3857 = EXCLUDED.geom_3857,
                        tags = EXCLUDED.tags,
                        highway = EXCLUDED.highway,
                        name = EXCLUDED.name,
                        lanes = EXCLUDED.lanes,
                        maxspeed = EXCLUDED.maxspeed
                    """,
                    way_data
                )
                insert_time = time.time() - start_time
                logger.success(
                    f"Batch inserted {len(way_data)} ways "
                    f"in {insert_time:.2f}s"
                )
        
        logger.success(f"Saved {saved_count} ways to osm.ways")
        return saved_count
    
    async def start_process_job(
        self,
        osm_data_path: str,
        capacity_mode: str
    ) -> str:
        """Start graph processing job."""
        job_id = str(uuid.uuid4())
        
        self.jobs[job_id] = {
            "type": "process",
            "status": "started",
            "osm_data_path": osm_data_path,
            "capacity_mode": capacity_mode,
            "progress": 0.0
        }
        
        logger.info(f"Process job started: {job_id}")
        
        return job_id
    
    async def run_process_job(self, job_id: str):
        """
        Run graph processing job (background).
        
        Steps:
        1. Load OSM JSON
        2. Build nodes table
        3. Build edges table
        4. Calculate bearings (ST_Azimuth)
        5. Calculate capacity
        6. Pre-compute geom_3857
        7. Create spatial indexes
        
        TODO: Implement full pipeline.
        """
        logger.info(f"Running process job: {job_id}")
        
        self.jobs[job_id]["status"] = "running"
        
        try:
            # TODO: Implement graph building pipeline
            
            self.jobs[job_id]["status"] = "done"
            self.jobs[job_id]["progress"] = 1.0
            
        except Exception as e:
            logger.error(f"Process job failed: {e}", exc_info=e)
            self.jobs[job_id]["status"] = "error"
            self.jobs[job_id]["error"] = str(e)
    
    async def get_job_status(self, job_id: str) -> Dict:
        """Get job status."""
        if job_id not in self.jobs:
            return {
                "job_id": job_id,
                "status": "not_found"
            }
        
        return {
            "job_id": job_id,
            **self.jobs[job_id]
        }
    
    def _zxy_to_bbox(self, z: int, x: int, y: int) -> tuple:
        """
        Convert Web Mercator tile coordinates to WGS84 bbox.
        
        Returns: (west, south, east, north)
        """
        import math
        
        n = 2.0 ** z
        west_lng = x / n * 360.0 - 180.0
        east_lng = (x + 1) / n * 360.0 - 180.0
        
        north_lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        north_lat = math.degrees(north_lat_rad)
        
        south_lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
        south_lat = math.degrees(south_lat_rad)
        
        return (west_lng, south_lat, east_lng, north_lat)
    
    def _bbox_to_osm_tiles(self, bbox: tuple) -> List[tuple]:
        """
        Calculate OSM tiles that INTERSECT given bbox.
        
        MONOLITHIC mode: returns single tile (west, south) of default bbox
        TILED mode: returns list of tile_keys that intersect bbox
        
        Args:
            bbox: (west, south, east, north)
        
        Returns:
            List of tile_keys [(lon, lat), ...] that intersect bbox
        """
        west, south, east, north = bbox
        
        # MONOLITHIC mode - single tile for entire default bbox
        if self.tile_size_degrees is None:
            return [(self.default_bbox["west"], self.default_bbox["south"])]
        
        tiles = []
        
        # TILED mode - Calculate tile grid starting points
        start_lon = (west // self.tile_size_degrees) * self.tile_size_degrees
        start_lat = (south // self.tile_size_degrees) * self.tile_size_degrees
        
        # Iterate through tiles that MIGHT intersect
        lat = start_lat
        while lat < north + self.tile_size_degrees:
            lon = start_lon
            while lon < east + self.tile_size_degrees:
                # Check if tile (lon, lat) intersects bbox
                tile_west = lon
                tile_south = lat
                tile_east = lon + self.tile_size_degrees
                tile_north = lat + self.tile_size_degrees
                
                # Intersection check (AABB collision)
                if not (tile_east <= west or tile_west >= east or
                        tile_north <= south or tile_south >= north):
                    tile_key = (
                        round(lon, 2),
                        round(lat, 2)
                    )
                    tiles.append(tile_key)
                
                lon += self.tile_size_degrees
            lat += self.tile_size_degrees
        
        return tiles
    
    def _bbox_intersects_default(self, bbox: tuple) -> bool:
        """
        Check if bbox intersects with default bbox.
        
        Args:
            bbox: (west, south, east, north)
        
        Returns:
            True if intersects
        """
        west, south, east, north = bbox
        default = self.default_bbox
        
        # No intersection if:
        # - bbox completely to the right of default (west >= east)
        # - bbox completely to the left of default (east <= west)
        # - bbox completely above default (south >= north)
        # - bbox completely below default (north <= south)
        # Use strict inequalities to correctly handle edge cases
        if (west > default["east"] or
                east < default["west"] or
                south > default["north"] or
                north < default["south"]):
            return False
        
        return True
    
    def _is_tile_in_bounds(self, tile_key: tuple) -> bool:
        """
        Check if OSM tile is within default bounds.
        
        MONOLITHIC mode: always returns True (single tile = entire bbox)
        TILED mode: checks if tile intersects bounds
        
        Args:
            tile_key: (lon, lat) or (west, south) for monolith
        
        Returns:
            True if tile is within bounds
        """
        # MONOLITHIC mode - single tile always in bounds
        if self.tile_size_degrees is None:
            return True
        
        lon, lat = tile_key
        bounds = self.default_bbox
        
        # TILED mode - Tile at (lon, lat) covers [lon, lon+tile_size) x [lat, lat+tile_size)
        # Check if tile intersects bounds
        if (lon >= bounds["east"] or
                lon + self.tile_size_degrees <= bounds["west"] or
                lat >= bounds["north"] or
                lat + self.tile_size_degrees <= bounds["south"]):
            return False
        
        return True
    
    async def _mark_tile_failed(self, tile_key: tuple, error: str, attempts: int):
        """
        Mark tile as failed in cached_tiles table.
        
        Args:
            tile_key: (lon, lat) or (west, south) for monolith
            error: Error message
            attempts: Number of download attempts
        """
        tile_bbox = self._tile_to_bbox(tile_key)
        tile_key_str = self._tile_key_to_str(tile_key)
        
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO osm.cached_tiles (
                    tile_key, min_lon, min_lat, max_lon, max_lat, 
                    bbox, total_ways, download_status, download_error, 
                    download_attempts, last_download_attempt
                )
                VALUES ($1, $2, $3, $4, $5, 
                    ST_MakeEnvelope($2, $3, $4, $5, 4326), 
                    0, 'failed', $6, $7, CURRENT_TIMESTAMP)
                ON CONFLICT (tile_key) DO UPDATE SET
                    download_status = 'failed',
                    download_error = $6,
                    download_attempts = osm.cached_tiles.download_attempts + $7,
                    last_download_attempt = CURRENT_TIMESTAMP
            """, 
                tile_key_str,
                tile_bbox[0], tile_bbox[1], tile_bbox[2], tile_bbox[3],
                error,
                attempts
            )
        
        logger.info(
            f"Tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
            f"marked as FAILED in DB"
        )
    
    async def get_ways_count(self) -> int:
        """Get total number of ways in database."""
        async with self.db_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM osm.ways")
            return count or 0
    
    async def _notify_tile_ready(self, tile_key: tuple) -> None:
        """
        Notify WebSocket clients that OSM tile is ready.
        
        Calculates which MVT tiles are affected and sends notification.
        """
        if not self.ws_notify_callback:
            return
        
        # Calculate affected MVT tiles
        # For simplicity, notify about zoom level 14 (where MVT ~= OSM tile)
        # In production, calculate actual affected MVT tiles
        tile_bbox = self._tile_to_bbox(tile_key)
        
        # Example: notify about a single representative MVT tile
        # Real implementation should calculate all affected MVT tiles
        import math
        
        # Web Mercator tile calculation for zoom 14
        z = 14
        lon_min, lat_min, lon_max, lat_max = tile_bbox
        
        # Convert to tile coordinates
        n = 2 ** z
        x_min = int((lon_min + 180) / 360 * n)
        y_min = int((1 - math.log(
            math.tan(math.radians(lat_max)) +
            1 / math.cos(math.radians(lat_max))
        ) / math.pi) / 2 * n)
        
        x_max = int((lon_max + 180) / 360 * n)
        y_max = int((1 - math.log(
            math.tan(math.radians(lat_min)) +
            1 / math.cos(math.radians(lat_min))
        ) / math.pi) / 2 * n)
        
        # Generate list of affected tiles
        affected_tiles = []
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                affected_tiles.append([z, x, y])
        
        # Send notification
        try:
            await self.ws_notify_callback({
                "type": "tiles_ready",
                "tiles": affected_tiles,
                "osm_tile": {
                    "lon": tile_key[0],
                    "lat": tile_key[1]
                }
            })
            logger.info(
                f"[WS] Notified clients: OSM tile "
                f"[{tile_key[0]:.2f}, {tile_key[1]:.2f}] ready, "
                f"{len(affected_tiles)} MVT tiles affected"
            )
        except Exception as e:
            logger.error(f"[WS] Notification failed: {e}")
    
    async def get_mvt_tile(self, z: int, x: int, y: int) -> dict:
        """
        Generate Mapbox Vector Tile (MVT) for given tile coordinates.
        
        NEW: Automatically downloads missing OSM tiles if needed.
        
        Args:
            z: Zoom level
            x: Tile X coordinate
            y: Tile Y coordinate
        
        Returns:
            {
                "mvt": bytes,
                "status": "ready" | "downloading" | "outside"
            }
        """
        # Convert z/x/y to bbox
        bbox = self._zxy_to_bbox(z, x, y)
        logger.debug(
            f"MVT tile [{z}/{x}/{y}] -> bbox "
            f"[{bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f}]"
        )
        
        # Check if MVT tile intersects with default bbox
        if not self._bbox_intersects_default(bbox):
            logger.debug(
                f"MVT [{z}/{x}/{y}] outside default bbox"
            )
            return {"mvt": b"", "status": "outside"}
        
        # Calculate which OSM tiles cover this MVT tile
        osm_tiles = self._bbox_to_osm_tiles(bbox)
        logger.trace(
            f"MVT [{z}/{x}/{y}] requires {len(osm_tiles)} OSM tiles"
        )
        
        # Download-on-demand: check tile status WITHOUT blocking
        downloading = False
        for tile_key in osm_tiles:
            # Server-side validation: only download tiles within bounds
            if not self._is_tile_in_bounds(tile_key):
                logger.trace(
                    f"OSM tile [{tile_key[0]:.2f}, {tile_key[1]:.2f}] "
                    f"outside bounds, skipping download"
                )
                continue
            
            # Check if already downloading
            if tile_key in self.downloading_tiles:
                downloading = True
                continue
            
            # Check if exists in DB
            check = await self.check_tile_in_db(tile_key)
            if not check["exists"]:
                # Start download in background (non-blocking)
                asyncio.create_task(self.ensure_tile_downloaded(tile_key))
                downloading = True
        
        # Generate MVT from available data
        async with self.db_pool.acquire() as conn:
            # ST_TileEnvelope generates tile bbox for given z/x/y
            # ST_AsMVT generates MVT protobuf
            mvt = await conn.fetchval("""
                SELECT ST_AsMVT(tile, 'ways', 4096, 'geom')
                FROM (
                    SELECT
                        osm_id,
                        highway,
                        name,
                        ST_AsMVTGeom(
                            geom_3857,
                            ST_TileEnvelope($1, $2, $3),
                            4096,
                            256,
                            true
                        ) AS geom
                    FROM osm.ways
                    WHERE geom_3857 && ST_TileEnvelope($1, $2, $3)
                    AND highway IN (
                        'motorway', 'motorway_link',
                        'trunk', 'trunk_link',
                        'primary', 'primary_link',
                        'secondary', 'secondary_link',
                        'tertiary', 'tertiary_link',
                        'unclassified', 'residential',
                        'living_street', 'service'
                    )
                ) AS tile
            """, z, x, y)
        
        mvt_size = len(mvt) if mvt else 0
        logger.debug(f"MVT [{z}/{x}/{y}] generated: {mvt_size} bytes")
        
        # Determine status
        if downloading and mvt_size == 0:
            status = "downloading"
        elif mvt_size > 0:
            status = "ready"
        else:
            status = "downloading"  # Assume downloading if no data yet
        
        return {"mvt": mvt if mvt else b"", "status": status}
