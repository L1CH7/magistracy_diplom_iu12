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
import json
import os
from loguru import logger
from typing import Dict, List


class DataProcessorManager:
    """
    Process OSM data into navigation graph.
    
    Design:
    - Async jobs (long-running operations)
    - Job status tracking
    - PostgreSQL + PostGIS for storage
    """
    
    def __init__(self):
        # Database connection
        self.db_pool: asyncpg.Pool = None
        
        # Job registry
        self.jobs: Dict[str, Dict] = {}
        
        # Config from environment
        self.db_host = os.getenv("POSTGRES_HOST", "localhost")
        self.db_port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.db_name = os.getenv("POSTGRES_DB", "osm")
        self.db_user = os.getenv("POSTGRES_USER", "postgres")
        self.db_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        
        logger.info("DataProcessorManager initialized")
    
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
                    min_size=2,
                    max_size=10,
                    timeout=5
                )
                
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
    
    async def shutdown(self):
        """Shutdown manager."""
        if self.db_pool:
            await self.db_pool.close()
        
        logger.info("Data Processor shutdown complete")
    
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
    
    async def run_fetch_job(self, job_id: str):
        """
        Run fetch job (background).
        
        Fetches OSM data via Overpass API and saves to PostgreSQL.
        """
        from src.data.osm_overpass import fetch_overpass, build_highway_query
        
        logger.info(f"Running fetch job: {job_id}")
        
        self.jobs[job_id]["status"] = "running"
        
        try:
            job_data = self.jobs[job_id]
            bbox = job_data["bbox"]  # [min_lon, min_lat, max_lon, max_lat]
            highway_types = job_data.get("highway_types", [])
            
            # Build Overpass query (south, west, north, east)
            query = build_highway_query(
                (bbox[1], bbox[0], bbox[3], bbox[2])
            )
            
            # Fetch from Overpass API
            logger.info(f"Fetching OSM data for bbox {bbox}")
            osm_data = fetch_overpass(query, timeout=180)
            
            # Count elements
            elements = osm_data.get("elements", [])
            ways_count = len([e for e in elements if e.get("type") == "way"])
            
            logger.info(f"Fetched {len(elements)} elements, {ways_count} ways")
            
            # Save to PostgreSQL osm.ways table
            await self._save_ways_to_db(osm_data)
            
            self.jobs[job_id]["status"] = "done"
            self.jobs[job_id]["progress"] = 1.0
            self.jobs[job_id]["ways_count"] = ways_count
            
            logger.success(f"Fetch job complete: {job_id}")
            
        except Exception as e:
            logger.error(f"Fetch job failed: {str(e)}", exc_info=True)
            self.jobs[job_id]["status"] = "error"
            self.jobs[job_id]["error"] = str(e)
    
    async def _save_ways_to_db(self, osm_data: dict):
        """Save OSM ways to PostgreSQL osm.ways table."""
        elements = osm_data.get("elements", [])
        ways = [e for e in elements if e.get("type") == "way"]
        
        logger.info(f"Saving {len(ways)} ways to osm.ways")
        
        async with self.db_pool.acquire() as conn:
            for way in ways:
                osm_id = way.get("id")
                tags = way.get("tags", {})
                highway = tags.get("highway")
                
                if not highway:
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
                
                # Insert or update way
                await conn.execute("""
                    INSERT INTO osm.ways (
                        osm_id, geom, geom_3857, tags, highway, name, lanes,
                        maxspeed
                    ) VALUES (
                        $1,
                        ST_GeomFromGeoJSON($2),
                        ST_Transform(ST_GeomFromGeoJSON($2), 3857),
                        $3::jsonb,
                        $4,
                        $5,
                        $6::integer,
                        $7
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
                    osm_id,
                    json.dumps(geom_json),
                    json.dumps(tags),
                    highway,
                    tags.get("name"),
                    (int(tags.get("lanes"))
                     if tags.get("lanes") and tags.get("lanes").isdigit()
                     else None),
                    tags.get("maxspeed")
                )
        
        logger.success(f"Saved {len(ways)} ways to osm.ways")
    
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
