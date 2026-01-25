"""
Tile Download Handler - manages OSM tile downloading and saving.

Responsibilities:
- Download OSM data from Overpass API
- Save ways to database (batch insert)
- Update cached_tiles metadata
- Integrate with TaskManager for progress tracking
"""

import json
import aiohttp
import asyncio
from typing import Optional, Tuple, List, Set
from loguru import logger
import time

from ..db.pool import DatabasePool
from ..db.queries import OSMQueries, format_tile_key
from ..state.task_manager import TaskManager, TaskPhase
from .utils import split_bbox

class TileDownloadHandler:
    """Handles tile download operations."""
    
    def __init__(
        self,
        db: DatabasePool,
        task_manager: TaskManager,
        overpass_servers: List[str],
        timeout: int = 300,
        tile_size: float = 0.05,
        cpu_cores: int = 0
    ):
        self.db = db
        self.task_manager = task_manager
        self.overpass_servers = overpass_servers
        self.timeout = timeout
        self.tile_size = tile_size
        self._server_failures = {server: 0 for server in overpass_servers}
        
        # Concurrency control
        # If cpu_cores is 0, use reasonable default for network I/O (e.g., 5-10) 
        # since overpass servers have rate limits.
        # For data processing logic, it might be CPU bound, but here acts as download throttle.
        limit = cpu_cores if cpu_cores > 0 else 5
        self.semaphore = asyncio.Semaphore(limit)
        
        # Task cancellation
        self._active_tasks: Set[asyncio.Task] = set()
        self._cancel_requested = False

    async def cancel_all_downloads(self):
        """Cancel all active download tasks."""
        self._cancel_requested = True
        logger.warning(f"Cancelling {len(self._active_tasks)} active download tasks...")
        
        for task in self._active_tasks:
            task.cancel()
            
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            
        self._active_tasks.clear()
        self._cancel_requested = False
        logger.info("All downloads cancelled.")

    async def download_area(
        self,
        bbox: Tuple[float, float, float, float],
        overwrite: bool = True
    ) -> dict:
        """
        Download all tiles within the bbox.
        
        Args:
            bbox: (west, south, east, north)
            overwrite: If True, redownload existing tiles.
        """
        west, south, east, north = bbox
        
        # 1. Split area into tiles
        tiles = list(split_bbox(west, south, east, north, self.tile_size))
        total_tiles = len(tiles)
        
        if total_tiles == 0:
            return {"status": "empty", "message": "No tiles in area"}
            
        logger.info(f"Starting area download: {total_tiles} tiles in bbox {bbox}")
        
        # 2. Track overall progress
        group_task_id = self.task_manager.create_task(
            "area_download",
            items_total=total_tiles
        )
        
        processed_count = 0
        success_count = 0
        failed_count = 0
        
        async def process_tile(tile_bbox):
            nonlocal processed_count, success_count, failed_count
            
            # Check for cancellation
            if self._cancel_requested:
                return

            try:
                # Use standard tile key relative to tile grid (approximate for logging)
                msg = await self.download_tile(tile_bbox, overwrite=overwrite)
                if msg["status"] == "complete":
                    success_count += 1
                else:
                    failed_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failed_count += 1
                logger.error(f"Tile processing failed: {e}")
            finally:
                processed_count += 1
                # Log progress every 5%
                if total_tiles > 20 and processed_count % (total_tiles // 20) == 0:
                     percent = (processed_count / total_tiles) * 100
                     logger.info(f"Area download progress: {processed_count}/{total_tiles} tiles ({percent:.1f}%)")
                     self.task_manager.update_progress(
                         group_task_id,
                         percent,
                         TaskPhase.DOWNLOADING,
                         f"Processed {processed_count}/{total_tiles} tiles"
                     )

        # 3. Create tasks
        to_run = []
        for t_bbox in tiles:
           to_run.append(process_tile(t_bbox))
           
        # 4. Run with concurrency limit
        # We need to wrap each in semaphore
        async def sem_task(coro):
            async with self.semaphore:
                task = asyncio.create_task(coro)
                self._active_tasks.add(task)
                try:
                    await task
                except asyncio.CancelledError:
                    pass # Handled in cancel_all
                finally:
                    self._active_tasks.discard(task)

        tasks = [sem_task(t) for t in to_run]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.warning("Area download cancelled")
            self.task_manager.mark_failed(group_task_id, "Cancelled by user")
            return {"status": "cancelled"}
            
        self.task_manager.mark_complete(
            group_task_id,
            f"Completed: {success_count} success, {failed_count} failed"
        )
        
        return {
            "status": "complete",
            "total": total_tiles,
            "success": success_count,
            "failed": failed_count
        }

    async def download_tile(
        self,
        bbox: Tuple[float, float, float, float],
        overwrite: bool = True
    ) -> dict:
        """
        Download and save single tile.
        
        Args:
            tile_key: (lon, lat) tile identifier (derived from bbox)
            bbox: (west, south, east, north) bounding box
        """
        # tile_key for DB is based on the south-west corner
        tile_key_tuple = (bbox[0], bbox[1])
        tile_str = format_tile_key(*tile_key_tuple)
        
        # Check if exists (unless overwrite)
        # Check if exists (unless overwrite)
        if not overwrite:
            try:
                # Check status in DB
                async with self.db.acquire() as conn:
                    status = await conn.fetchval(
                        "SELECT download_status FROM osm.cached_tiles WHERE tile_key = $1",
                        tile_str
                    )
                    if status == "complete":
                        logger.trace(f"Tile {tile_str} exists and complete, skipping.")
                        return {"status": "skipped", "message": "Already exists"}
            except Exception as e:
                logger.warning(f"Failed to check tile status for {tile_str}: {e}")
                # Proceed to download if check fails
                pass

        download_task_id = self.task_manager.create_task(
            "tile_download",
            tile_key=tile_str
        )
        
        try:
            # Mark as downloading
            await self._insert_or_update_tile(
                tile_str, bbox, "downloading", 0, ""
            )
            
            # Download
            osm_data = await self._download_osm_data(bbox)
            
            # Extract
            elements = osm_data.get("elements", [])
            ways = [e for e in elements if e.get("type") == "way"]
            total_ways = len(ways)
            
            # Save
            saved_count = await self._save_ways_to_db(
                ways,
                elements,
                download_task_id,
                total_ways
            )
            
            # Update status
            await self._update_tile_status(
                tile_str, "complete", saved_count, ""
            )
            
            # Broadcast
            await self._broadcast_ways_updated()

            self.task_manager.mark_complete(download_task_id, f"Saved {saved_count} ways")
            logger.trace(f"Tile [{tile_str}] completed. Ways: {saved_count}")
            
            return {
                "status": "complete",
                "ways_count": saved_count
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Tile [{tile_str}] failed: {error_msg}")
            
            await self._update_tile_status(
                tile_str, "failed", 0, error_msg
            )
            self.task_manager.mark_failed(download_task_id, error_msg)
            
            return {
                "status": "failed",
                "error": error_msg
            }
    
    async def _download_osm_data(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> dict:
        """
        Download OSM data from Overpass API.
        
        Args:
            bbox: (west, south, east, north)
        
        Returns:
            OSM JSON data
        """
        west, south, east, north = bbox
        
        # Build Overpass QL query (same as old osm_loader.py)
        # Build Overpass QL query
        query = f"""
        [out:json][timeout:{self.timeout}];
        (
          // 1. Graph edge filtering by whitelist
          way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|unclassified|service|road|track|bus_guideway|escape)$"]({south},{west},{north},{east});
          
          // 2. Turn Restrictions extraction
          relation["type"="restriction"]({south},{west},{north},{east});
          
          // 3. Point barriers extraction (Traffic Calming / Barriers)
          node["barrier"~"gate|boom|bollard|block|wall|lift_gate|sliding_gate"]({south},{west},{north},{east});
          
          // 4. Access restrictions extraction
          way["access"="private"]({south},{west},{north},{east});
          way["access"="no"]({south},{west},{north},{east});
          way["motor_vehicle"="no"]({south},{west},{north},{east});
          way["service"="driveway"]({south},{west},{north},{east});
        );
        
        // Output phase:
        out body;  // Metadata (ID and tags)
        >;         // Recurse down
        out skel qt; // Skeleton geometry
        """
        
        # Try servers in order of least failures
        sorted_servers = sorted(
            self.overpass_servers,
            key=lambda s: self._server_failures[s]
        )
        
        last_error = None
        
        for server in sorted_servers:
            try:
                # Use asyncio.sleep to be nice to servers if we had failures?
                # For now just go.
                headers = {
                    "User-Agent": "DiplomDataProcessor/1.0 (bmstu-student-project; contact: admin@example.com)",
                    "Accept-Encoding": "gzip"
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{server}/api/interpreter",
                        data={"data": query},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as response:
                        if response.status == 429: # Too many requests
                             logger.warning(f"Overpass {server} 429 Too Many Requests, backing off...")
                             await asyncio.sleep(5) 
                             raise Exception("Too many requests")

                        response.raise_for_status()
                        data = await response.json()
                        
                        # Reset failure count on success
                        self._server_failures[server] = 0
                        
                        return data
                        
            except Exception as e:
                last_error = e
                self._server_failures[server] += 1
                # logger.warning(
                #    f"Overpass server {server} failed: {e}"
                # )
                continue
        
        # All servers failed
        raise RuntimeError(
            f"All Overpass servers failed. Last error: {last_error}"
        )
    
    async def _save_ways_to_db(
        self,
        ways: List[dict],
        elements: List[dict],
        task_id: str,
        total_ways: int
    ) -> int:
        """
        Save ways to database using batch insert.
        
        Args:
            ways: List of OSM way objects
            elements: All OSM elements (for node lookup)
            task_id: Task ID for progress tracking
            total_ways: Total ways count
        
        Returns:
            Number of ways saved
        """
    @staticmethod
    def _prepare_batch_data(ways: List[dict], elements: List[dict]) -> Tuple[List[tuple], int]:
        """
        Prepare data for batch insert (CPU bound).
        Run this in a thread pool to avoid blocking asyncio loop.
        """
        batch_data = []
        saved_count = 0
        
        # Build node lookup
        node_map = {
            e["id"]: e
            for e in elements
            if e.get("type") == "node"
        }
        
        # Drivable road types
        drivable_types = {
            'motorway', 'motorway_link',
            'trunk', 'trunk_link',
            'primary', 'primary_link',
            'secondary', 'secondary_link',
            'tertiary', 'tertiary_link',
            'unclassified', 'residential',
            'living_street', 'service',
            'road', 'track',
            'bus_guideway', 'escape'
        }
        
        for way in ways:
            osm_id = way.get("id")
            tags = way.get("tags", {})
            highway = tags.get("highway")
            
            # Filter: only drivable roads
            if highway not in drivable_types:
                continue
            
            # Build LineString from nodes
            nodes = way.get("nodes", [])
            if len(nodes) < 2:
                continue
            
            # Get node coordinates
            node_coords = []
            for node_id in nodes:
                node = node_map.get(node_id)
                if node:
                    node_coords.append([node["lon"], node["lat"]])
            
            if len(node_coords) < 2:
                continue
            
            # Build geometry as LineString
            geom_json = {
                "type": "LineString",
                "coordinates": node_coords
            }
            
            # Collect data for batch insert
            batch_data.append((
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
            
        return batch_data, saved_count

    async def _save_ways_to_db(
        self,
        ways: List[dict],
        elements: List[dict],
        task_id: str,
        total_ways: int
    ) -> int:
        """
        Save ways to database using batch insert.
        """
        # Offload CPU-bound preparation to thread pool
        loop = asyncio.get_running_loop()
        batch_data, saved_count = await loop.run_in_executor(
            None, 
            self._prepare_batch_data, 
            ways, 
            elements
        )
        
        # Batch insert (I/O bound)
        if batch_data:
            async with self.db.acquire() as conn:
                await conn.executemany(
                    OSMQueries.BATCH_INSERT_WAYS,
                    batch_data
                )
        
        return saved_count
    
    async def _insert_or_update_tile(
        self,
        tile_key: str,
        bbox: Tuple[float, float, float, float],
        status: str,
        ways_count: int,
        error_message: Optional[str]
    ) -> None:
        """Insert or update tile metadata."""
        west, south, east, north = bbox
        
        try:
            async with self.db.acquire() as conn:
                await conn.execute(
                    OSMQueries.INSERT_TILE_METADATA,
                    tile_key,
                    status,
                    ways_count,
                    west, south, east, north
                )
        except Exception as e:
            logger.error(
                f"Failed to insert/update tile {tile_key}: {e}"
            )
            raise
    
    async def _update_tile_status(
        self,
        tile_key: str,
        status: str,
        ways_count: int,
        error_message: Optional[str]
    ) -> None:
        """Update tile status in cached_tiles table."""
        try:
            async with self.db.acquire() as conn:
                await conn.execute(
                    OSMQueries.UPDATE_TILE_STATUS,
                    tile_key,
                    status,
                    ways_count,
                    error_message or ""  # Never pass None
                )
        except Exception as e:
            logger.error(
                f"Failed to update tile {tile_key}: {e}"
            )
            raise
    
    async def _broadcast_ways_updated(self) -> None:
        """Broadcast WebSocket event: ways updated and tiles invalidated."""
        try:
            # Broadcast that tiles should be refreshed (new data available)
            from src.api.websocket import broadcast_tiles_invalidated, broadcast_ways_updated
            await broadcast_tiles_invalidated()
            
            # Also broadcast count for statistics
            # We can optimize this by not counting every time if needed, 
            # but for now let's be accurate.
            async with self.db.acquire() as conn:
                count = await conn.fetchval("SELECT COUNT(*) FROM osm.ways")
            await broadcast_ways_updated(count)
            
            logger.trace(f"Broadcasted update: tiles invalidated, ways={count}")
            
        except Exception as e:
            logger.error(f"Failed to broadcast ways_updated: {e}")

