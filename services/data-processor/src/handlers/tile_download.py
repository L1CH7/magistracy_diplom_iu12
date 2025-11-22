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
from typing import Optional, Tuple, List
from loguru import logger

from ..db.pool import DatabasePool
from ..db.queries import OSMQueries, format_tile_key
from ..state.task_manager import TaskManager, TaskPhase


class TileDownloadHandler:
    """Handles tile download operations."""
    
    def __init__(
        self,
        db: DatabasePool,
        task_manager: TaskManager,
        overpass_servers: List[str],
        timeout: int = 300
    ):
        self.db = db
        self.task_manager = task_manager
        self.overpass_servers = overpass_servers
        self.timeout = timeout
        self._server_failures = {server: 0 for server in overpass_servers}
    
    async def download_tile(
        self,
        tile_key: Tuple[float, float],
        bbox: Tuple[float, float, float, float]
    ) -> dict:
        """
        Download and save single tile.
        
        Args:
            tile_key: (lon, lat) tile identifier
            bbox: (west, south, east, north) bounding box
        
        Returns:
            {"status": "complete"|"failed", "ways_count": int}
        """
        tile_str = format_tile_key(*tile_key)
        
        # Create task for tracking
        task_id = self.task_manager.create_task(
            "tile_download",
            tile_key=tile_str
        )
        
        try:
            # Mark as downloading in DB (insert if not exists)
            await self._insert_or_update_tile(
                tile_str, bbox, "downloading", 0, ""  # Empty string not None
            )
            
            # Download OSM data
            self.task_manager.update_progress(
                task_id,
                10.0,
                TaskPhase.DOWNLOADING,
                f"Downloading OSM data for {tile_str}"
            )
            
            osm_data = await self._download_osm_data(bbox)
            
            # Extract ways
            elements = osm_data.get("elements", [])
            ways = [e for e in elements if e.get("type") == "way"]
            total_ways = len(ways)
            
            logger.info(
                f"Tile [{tile_str}] downloaded {total_ways} ways"
            )
            
            # Save to database
            self.task_manager.update_progress(
                task_id,
                50.0,
                TaskPhase.SAVING,
                f"Saving {total_ways} ways",
                items_total=total_ways
            )
            
            saved_count = await self._save_ways_to_db(
                ways,
                elements,
                task_id,
                total_ways
            )
            
            # Mark as complete
            await self._update_tile_status(
                tile_str, "complete", saved_count, ""  # Empty string not None
            )
            
            self.task_manager.mark_complete(
                task_id,
                f"Tile {tile_str} downloaded: {saved_count} ways"
            )
            
            logger.success(
                f"Tile [{tile_str}] completed: {saved_count} ways"
            )
            
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
            
            self.task_manager.mark_failed(task_id, error_msg)
            
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
        query = f"""
        [out:json][timeout:{self.timeout}];
        (
          way["highway"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """
        
        # Try servers in order of least failures
        sorted_servers = sorted(
            self.overpass_servers,
            key=lambda s: self._server_failures[s]
        )
        
        last_error = None
        
        for server in sorted_servers:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{server}/api/interpreter",
                        data={"data": query},
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as response:
                        response.raise_for_status()
                        data = await response.json()
                        
                        # Reset failure count on success
                        self._server_failures[server] = 0
                        
                        return data
                        
            except Exception as e:
                last_error = e
                self._server_failures[server] += 1
                logger.warning(
                    f"Overpass server {server} failed: {e}"
                )
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
        import time
        
        start_time = time.time()
        batch_data = []
        saved_count = 0
        
        # Build node lookup
        node_map = {
            e["id"]: e
            for e in elements
            if e.get("type") == "node"
        }
        
        # Debug: check node_map size
        nodes_with_coords = sum(
            1 for n in node_map.values()
            if n.get("lat") and n.get("lon")
        )
        logger.debug(
            f"Node lookup: {len(node_map)} total nodes, "
            f"{nodes_with_coords} with coordinates"
        )
        
        # Drivable road types
        drivable_types = {
            'motorway', 'motorway_link',
            'trunk', 'trunk_link',
            'primary', 'primary_link',
            'secondary', 'secondary_link',
            'tertiary', 'tertiary_link',
            'unclassified', 'residential',
            'living_street', 'service'
        }
        
        # Debug: collect highway types and filter reasons
        highway_types = {}
        filter_stats = {
            "total": 0,
            "passed_highway": 0,
            "no_nodes": 0,
            "no_coords": 0,
            "success": 0
        }
        
        for idx, way in enumerate(ways, start=1):
            filter_stats["total"] += 1
            
            osm_id = way.get("id")
            tags = way.get("tags", {})
            highway = tags.get("highway")
            
            # Debug: count highway types
            highway_types[highway] = highway_types.get(highway, 0) + 1
            
            # Filter: only drivable roads
            if highway not in drivable_types:
                continue
            
            filter_stats["passed_highway"] += 1
            
            # Build LineString from nodes
            nodes = way.get("nodes", [])
            if len(nodes) < 2:
                filter_stats["no_nodes"] += 1
                continue
            
            # Get node coordinates
            node_coords = []
            for node_id in nodes:
                node = node_map.get(node_id)
                if node:
                    node_coords.append([node["lon"], node["lat"]])
            
            if len(node_coords) < 2:
                filter_stats["no_coords"] += 1
                continue
            
            filter_stats["success"] += 1
            
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
            
            # Progress update every 10%
            if idx % max(1, total_ways // 10) == 0:
                progress = 50.0 + (idx / total_ways) * 50.0
                self.task_manager.update_progress(
                    task_id,
                    progress,
                    items_processed=idx
                )
        
        # Debug: log highway type distribution and filter stats
        logger.debug(
            f"Highway types in downloaded data: {highway_types}"
        )
        logger.debug(
            f"Filter stats: {filter_stats}"
        )
        logger.debug(
            f"Final result: {saved_count}/{total_ways} ways passed all filters"
        )
        
        # Batch insert
        if batch_data:
            async with self.db.acquire() as conn:
                await conn.executemany(
                    OSMQueries.BATCH_INSERT_WAYS,
                    batch_data
                )
        
        insert_time = time.time() - start_time
        logger.success(
            f"Batch inserted {len(batch_data)} ways in {insert_time:.2f}s"
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
                logger.info(
                    f"Tile [{tile_key}] metadata: {status}, {ways_count} ways"
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
                logger.info(
                    f"Tile [{tile_key}] → {status}"
                )
        except Exception as e:
            logger.error(
                f"Failed to update tile {tile_key}: {e}"
            )
            raise
