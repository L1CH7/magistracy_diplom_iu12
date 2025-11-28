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
            
            # Extract all element types
            elements = osm_data.get("elements", [])
            ways = [e for e in elements if e.get("type") == "way"]
            barriers = [e for e in elements if e.get("type") == "node" and "barrier" in e.get("tags", {})]
            restrictions = [e for e in elements if e.get("type") == "relation" and e.get("tags", {}).get("type") == "restriction"]
            
            total_ways = len(ways)
            total_barriers = len(barriers)
            total_restrictions = len(restrictions)
            
            logger.info(
                f"Tile [{tile_str}] downloaded: "
                f"{total_ways} ways, {total_barriers} barriers, {total_restrictions} restrictions"
            )
            
            # Save to database (50% - 90% progress)
            self.task_manager.update_progress(
                task_id,
                50.0,
                TaskPhase.SAVING,
                f"Saving {total_ways} ways",
                items_total=total_ways + total_barriers + total_restrictions
            )
            
            saved_ways = await self._save_ways_to_db(
                ways,
                elements,
                task_id,
                total_ways
            )
            
            # Save barriers (70%)
            self.task_manager.update_progress(
                task_id,
                70.0,
                TaskPhase.SAVING,
                f"Saving {total_barriers} barriers"
            )
            
            saved_barriers = await self._save_barriers_to_db(barriers)
            
            # Save restrictions (80%)
            self.task_manager.update_progress(
                task_id,
                80.0,
                TaskPhase.SAVING,
                f"Saving {total_restrictions} restrictions"
            )
            
            saved_restrictions = await self._save_restrictions_to_db(
                restrictions
            )
            
            total_saved = (
                saved_ways + saved_barriers + saved_restrictions
            )
            
            # Broadcast WebSocket event: ways updated
            await self._broadcast_ways_updated()
            
            # Mark as complete
            await self._update_tile_status(
                tile_str, "complete", total_saved, ""
            )
            
            self.task_manager.mark_complete(
                task_id,
                f"Tile {tile_str}: {saved_ways} ways, "
                f"{saved_barriers} barriers, {saved_restrictions} restrictions"
            )
            
            logger.success(
                f"Tile [{tile_str}] completed: {saved_ways} ways, "
                f"{saved_barriers} barriers, {saved_restrictions} restrictions"
            )
            
            return {
                "status": "complete",
                "ways_count": saved_ways,
                "barriers_count": saved_barriers,
                "restrictions_count": saved_restrictions
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
        
        # Build FULL Overpass QL query:
        # - Ways with highway (roads)
        # - Relations type=restriction (turn restrictions)
        # - Nodes with barrier (gates, bollards, etc)
        # - Ways with access restrictions (private, etc)
        query = f"""
        [out:json][timeout:{self.timeout}];
        (
          way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|unclassified|service|road|track|bus_guideway|escape)$"]({south},{west},{north},{east});
          relation["type"="restriction"]({south},{west},{north},{east});
          node["barrier"~"gate|boom|bollard|block|wall|lift_gate|sliding_gate"]({south},{west},{north},{east});
          way["access"="private"]({south},{west},{north},{east});
          way["access"="no"]({south},{west},{north},{east});
          way["motor_vehicle"="no"]({south},{west},{north},{east});
          way["service"="driveway"]({south},{west},{north},{east});
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
            
            # Parse oneway tag (keep as text for database)
            oneway_tag = tags.get("oneway")
            oneway = (
                oneway_tag
                if oneway_tag in ("yes", "no", "-1", "1", "true", "false")
                else None
            )

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
                tags.get("maxspeed"),
                oneway,
                tags.get("access"),
                tags.get("motor_vehicle"),
                tags.get("service")
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
    
    async def _save_barriers_to_db(self, barriers: List[dict]) -> int:
        """
        Save barriers (gates, bollards) to osm.barriers table.
        
        Args:
            barriers: List of OSM node objects with barrier tag
        
        Returns:
            Number of barriers saved
        """
        if not barriers:
            return 0
        
        import json
        
        batch_data = []
        
        for barrier in barriers:
            osm_id = barrier.get("id")
            lat = barrier.get("lat")
            lon = barrier.get("lon")
            tags = barrier.get("tags", {})
            
            if not (lat and lon):
                continue
            
            barrier_type = tags.get("barrier")
            access = tags.get("access")
            motor_vehicle = tags.get("motor_vehicle")
            name = tags.get("name")
            
            batch_data.append((
                osm_id,
                lon, lat,  # ST_SetSRID(ST_MakePoint(lon, lat), 4326)
                barrier_type,
                access,
                motor_vehicle,
                name,
                json.dumps(tags)
            ))
        
        if not batch_data:
            return 0
        
        async with self.db.pool.acquire() as conn:
            # Upsert (ON CONFLICT UPDATE)
            await conn.executemany(
                """
                INSERT INTO osm.barriers (
                    osm_id, geom, barrier_type, access,
                    motor_vehicle, name, tags
                )
                VALUES (
                    $1,
                    ST_SetSRID(ST_MakePoint($2, $3), 4326),
                    $4, $5, $6, $7, $8
                )
                ON CONFLICT (osm_id) DO UPDATE SET
                    geom = EXCLUDED.geom,
                    barrier_type = EXCLUDED.barrier_type,
                    access = EXCLUDED.access,
                    motor_vehicle = EXCLUDED.motor_vehicle,
                    name = EXCLUDED.name,
                    tags = EXCLUDED.tags
                """,
                batch_data
            )
        
        logger.info(f"Saved {len(batch_data)} barriers to osm.barriers")
        return len(batch_data)
    
    async def _save_restrictions_to_db(
        self,
        restrictions: List[dict]
    ) -> int:
        """
        Save turn restrictions to osm.turn_restrictions table.
        
        Args:
            restrictions: List of OSM relation objects (type=restriction)
        
        Returns:
            Number of restrictions saved
        """
        if not restrictions:
            return 0
        
        import json
        
        batch_data = []
        
        for restriction in restrictions:
            osm_id = restriction.get("id")
            tags = restriction.get("tags", {})
            members = restriction.get("members", [])
            
            # Try different restriction tag formats
            restriction_type = (
                tags.get("restriction") or
                tags.get("restriction:hgv") or
                tags.get("restriction:motorcar") or
                tags.get("restriction:bus")
            )
            
            # Skip if no restriction type found
            if not restriction_type:
                continue
            
            # Parse members: from, via, to
            from_way = None
            via_node = None
            via_way = None
            to_way = None
            
            for member in members:
                role = member.get("role")
                ref = member.get("ref")
                mtype = member.get("type")
                
                if role == "from" and mtype == "way":
                    from_way = ref
                elif role == "via" and mtype == "node":
                    via_node = ref
                elif role == "via" and mtype == "way":
                    via_way = ref
                elif role == "to" and mtype == "way":
                    to_way = ref
            
            batch_data.append((
                osm_id,
                restriction_type,
                from_way,
                via_node,
                via_way,
                to_way,
                json.dumps(tags)
            ))
        
        if not batch_data:
            return 0
        
        async with self.db.pool.acquire() as conn:
            # Upsert
            await conn.executemany(
                """
                INSERT INTO osm.turn_restrictions (
                    osm_relation_id, restriction_type, from_way_id,
                    via_node_id, via_way_id, to_way_id, tags
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (osm_relation_id) DO UPDATE SET
                    restriction_type = EXCLUDED.restriction_type,
                    from_way_id = EXCLUDED.from_way_id,
                    via_node_id = EXCLUDED.via_node_id,
                    via_way_id = EXCLUDED.via_way_id,
                    to_way_id = EXCLUDED.to_way_id,
                    tags = EXCLUDED.tags
                """,
                batch_data
            )
        
        logger.info(
            f"Saved {len(batch_data)} restrictions to "
            f"osm.turn_restrictions"
        )
        return len(batch_data)
    
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
    
    async def _broadcast_ways_updated(self) -> None:
        """Broadcast WebSocket event: ways updated."""
        try:
            # Query current way count
            async with self.db.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM osm.ways"
                )
            
            # Broadcast to all connected WebSocket clients
            from src.api.websocket import broadcast_ways_updated
            await broadcast_ways_updated(count)
            
            logger.info(f"Broadcasted ways_updated: {count} ways")
            
        except Exception as e:
            logger.error(f"Failed to broadcast ways_updated: {e}")
