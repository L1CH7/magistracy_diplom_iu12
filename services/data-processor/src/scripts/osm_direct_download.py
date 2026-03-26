#!/usr/bin/env python3
"""
OSM Direct Download Script - optimized standalone parallel downloader.
Implements Producer-Consumer pattern with non-blocking progress tracking.
"""

import sys
import os
import asyncio
import aiohttp
import asyncpg
import yaml
import json
import argparse
import time
from typing import List, Tuple, Dict, Optional, Set
from loguru import logger
from pathlib import Path

# Path resolution
script_path = Path(__file__).resolve()
module_root = None
for parent in script_path.parents:
    if (parent / "services").exists() or (parent / "configs").exists():
        module_root = parent
        break
if not module_root:
    module_root = script_path.parents[2]

sys.path.insert(0, str(module_root))
if (module_root / "services" / "data-processor").exists():
    sys.path.insert(0, str(module_root / "services" / "data-processor"))

try:
    from src.db.queries import OSMQueries, format_tile_key
    from src.handlers.utils import split_bbox
except ImportError:
    logger.error(f"Could not import src. Check sys.path: {sys.path}")
    raise

class OSMDirectDownloader:
    def __init__(self, db_config: Dict, overpass_config: Dict, bboxes_config: Dict, override: bool = False):
        self.db_config = db_config
        self.overpass_config = overpass_config
        self.bboxes_config = bboxes_config
        self.override = override
        self.pool = None
        self.tile_size = overpass_config.get('tile_size', 0.05)
        self.timeout = overpass_config.get('timeout', 300)
        self.servers = overpass_config.get('primary_servers', [])
        
        # Concurrency: 8 workers if 0, else what's in config
        cores = overpass_config.get('cpu_cores', 0)
        self.concurrency = cores if cores > 0 else 8
        
        # Internal state
        self._server_failures = {server: 0 for server in self.servers}
        self.save_queue = asyncio.Queue(maxsize=200) # Large enough to not block downloaders
        self.total_tiles = 0
        self.downloaded_count = 0
        self.saved_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.start_time = 0

    async def connect_db(self):
        self.pool = await asyncpg.create_pool(
            host=self.db_config['host'],
            port=self.db_config['port'],
            user=self.db_config['user'],
            password=self.db_config['password'],
            database=self.db_config['database'],
            min_size=self.concurrency + 2,
            max_size=self.concurrency + 10
        )
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS osm;")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS osm.turn_restrictions (
                    osm_id BIGINT PRIMARY KEY,
                    tags JSONB NOT NULL DEFAULT '{}'::jsonb,
                    members JSONB NOT NULL DEFAULT '[]'::jsonb
                );
            """)

    async def close_db(self):
        if self.pool:
            await self.pool.close()

    def _fmt_progress(self) -> str:
        processed = self.saved_count + self.skipped_count + self.failed_count
        percent = (processed / self.total_tiles * 100) if self.total_tiles > 0 else 0
        elapsed = time.time() - self.start_time
        return f"[{processed}/{self.total_tiles} | {percent:.1f}% | {elapsed:.1f}s]"

    async def download_all(self, bboxes: List[str] = None):
        if not bboxes:
            default_bbox = self.bboxes_config.get('default', 'moscow_mkad')
            bboxes = [default_bbox]
            logger.info(f"No bboxes specified, using default: {default_bbox}")

        all_tiles = []
        for bbox_name in bboxes:
            if bbox_name not in self.bboxes_config:
                logger.error(f"BBox '{bbox_name}' not found in bboxes.yaml")
                continue
            coords = self.bboxes_config[bbox_name]['coords']
            tiles = list(split_bbox(*coords, self.tile_size))
            logger.info(f"BBox '{bbox_name}' {coords} split into {len(tiles)} tiles")
            all_tiles.extend(tiles)

        self.total_tiles = len(all_tiles)
        if self.total_tiles == 0:
            logger.warning("No tiles to download.")
            return

        self.start_time = time.time()
        logger.info(f"Starting pipeline with {self.concurrency} workers for {self.total_tiles} tiles total")

        # Start consumer
        save_worker_task = asyncio.create_task(self.save_worker())
        
        # Fill download queue
        download_queue = asyncio.Queue()
        for tile in all_tiles:
            await download_queue.put(tile)
            
        # Start download workers
        workers = [asyncio.create_task(self.download_worker(download_queue, i)) for i in range(self.concurrency)]
            
        # Wait for all downloads to finish
        await download_queue.join()
        
        # Stop workers
        for w in workers: w.cancel()
        
        # Signal consumer to stop and wait
        await self.save_queue.put(None)
        await save_worker_task
        
        logger.success(f"Pipeline finished! {self._fmt_progress()}")

    async def download_worker(self, tile_queue: asyncio.Queue, worker_id: int):
        server_idx = worker_id % len(self.servers) if self.servers else 0
        
        while True:
            try:
                bbox = await tile_queue.get()
            except asyncio.CancelledError:
                break
                
            tile_str = format_tile_key(bbox[0], bbox[1])
            try:
                # 1. Check status
                if not self.override:
                    async with self.pool.acquire() as conn:
                        status = await conn.fetchval("SELECT download_status FROM osm.cached_tiles WHERE tile_key = $1", tile_str)
                        if status == 'complete':
                            self.skipped_count += 1
                            logger.debug(f"{self._fmt_progress()} Skipping {tile_str} (already complete)")
                            continue

                # 2. Mark as downloading
                async with self.pool.acquire() as conn:
                    await conn.execute(OSMQueries.INSERT_TILE_METADATA, tile_str, 'downloading', 0, *bbox)

                # 3. Fetch from Overpass
                logger.info(f"{self._fmt_progress()} Downloading {tile_str}...")
                data, server = await self._fetch_with_rotation(bbox, server_idx)
                server_idx = (server_idx + 1) % len(self.servers)
                self.downloaded_count += 1
                
                # 4. Delegate to save worker
                await self.save_queue.put((tile_str, bbox, data, server))
                
            except asyncio.CancelledError:
                # Put it back or just fail it? It will be retried next run anyway.
                raise
            except Exception as e:
                logger.error(f"{self._fmt_progress()} ERROR tile {tile_str}: {e}")
                self.failed_count += 1
                async with self.pool.acquire() as conn:
                    await conn.execute(OSMQueries.UPDATE_TILE_STATUS, tile_str, 'failed', 0, str(e))
            
            finally:
                tile_queue.task_done()

    async def save_worker(self):
        while True:
            item = await self.save_queue.get()
            if item is None:
                self.save_queue.task_done()
                break
                
            tile_str, bbox, data, server = item
            try:
                elements = data.get("elements", [])
                
                ways = [e for e in elements if e.get("type") == "way"]
                nodes = [e for e in elements if e.get("type") == "node" and e.get("tags") and e["tags"].get("barrier")]
                restrictions = [e for e in elements if e.get("type") == "relation" and e.get("tags") and e["tags"].get("type") == "restriction"]

                s_ways = await self._save_ways(ways, elements)
                s_nodes = await self._save_nodes(nodes)
                s_restr = await self._save_turn_restrictions(restrictions)

                self.saved_count += 1
                logger.info(f"{self._fmt_progress()} SAVED {tile_str} ({server}): {s_ways}w, {s_nodes}b, {s_restr}tr")
                
                async with self.pool.acquire() as conn:
                    await conn.execute(OSMQueries.UPDATE_TILE_STATUS, tile_str, 'complete', s_ways, "")
                    
            except Exception as e:
                logger.error(f"{self._fmt_progress()} SAVE ERROR {tile_str}: {e}")
                self.failed_count += 1
                async with self.pool.acquire() as conn:
                    await conn.execute(OSMQueries.UPDATE_TILE_STATUS, tile_str, 'failed', 0, f"DB Error: {e}")
            finally:
                self.save_queue.task_done()

    async def _fetch_with_rotation(self, bbox: Tuple[float, float, float, float], start_idx: int) -> Tuple[Dict, str]:
        west, south, east, north = bbox
        query = f"""
        [out:json][timeout:{self.timeout}];
        (
          way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|unclassified|service|road|track|bus_guideway|escape)$"]({south},{west},{north},{east});
          relation["type"="restriction"]({south},{west},{north},{east});
          // ПЕРЕКРЕСТКИ И БАРЬЕРЫ
          node["barrier"~"gate|boom|bollard|block|wall|lift_gate|sliding_gate"]({south},{west},{north},{east});
          way["barrier"~"fence|wall|gate|bollard|block"]({south},{west},{north},{east});
          way["access"~"private|no"]({south},{west},{north},{east});
          way["motor_vehicle"="no"]({south},{west},{north},{east});
          way["service"="driveway"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """
        
        num_servers = len(self.servers)
        async with aiohttp.ClientSession() as session:
            for i in range(num_servers):
                idx = (start_idx + i) % num_servers
                server = self.servers[idx]
                
                # Global failure cap to avoid repeated dead ends
                if self._server_failures[server] > 10 and i < num_servers - 1:
                    continue
                
                try:
                    async with session.post(f"{server}/api/interpreter", data={"data": query}, timeout=self.timeout) as resp:
                        if resp.status == 200:
                            if "json" not in resp.headers.get("Content-Type", ""):
                                self._server_failures[server] += 1
                                continue
                            data = await resp.json()
                            if "remark" in data:
                                self._server_failures[server] += 1
                                continue
                            self._server_failures[server] = 0
                            return data, server
                        elif resp.status == 429:
                            self._server_failures[server] += 5
                        else:
                            self._server_failures[server] += 1
                except Exception:
                    self._server_failures[server] += 1
                    
        raise RuntimeError(f"All servers failed for {west:.2f}_{south:.2f}")

    async def _save_ways(self, ways: List[Dict], all_elements: List[Dict]) -> int:
        if not ways: return 0
        node_map = {e["id"]: e for e in all_elements if e.get("type") == "node"}
        batch = []
        for w in ways:
            coords = []
            for nid in w.get("nodes", []):
                n = node_map.get(nid)
                if n: coords.append([n["lon"], n["lat"]])
            if len(coords) < 2: continue
            tags = w.get("tags", {})
            batch.append((w["id"], json.dumps({"type": "LineString", "coordinates": coords}), json.dumps(tags),
                          tags.get("highway", ""), tags.get("name"), 
                          int(tags["lanes"]) if tags.get("lanes", "").isdigit() else None,
                          tags.get("maxspeed")))
        if batch:
            async with self.pool.acquire() as conn:
                await conn.executemany(OSMQueries.BATCH_INSERT_WAYS, batch)
        return len(batch)

    async def _save_nodes(self, nodes: List[Dict]) -> int:
        if not nodes: return 0
        batch = [(n["id"], n["lon"], n["lat"], json.dumps(n.get("tags", {}))) for n in nodes]
        async with self.pool.acquire() as conn:
            await conn.executemany(OSMQueries.BATCH_INSERT_NODES, batch)
        return len(batch)

    async def _save_turn_restrictions(self, restrictions: List[Dict]) -> int:
        if not restrictions: return 0
        batch = [(r["id"], json.dumps(r.get("tags", {})), json.dumps(r.get("members", []))) for r in restrictions]
        async with self.pool.acquire() as conn:
            await conn.executemany(OSMQueries.BATCH_INSERT_TURN_RESTRICTIONS, batch)
        return len(batch)

def load_yml(p):
    with open(p) as f: return yaml.safe_load(f)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bboxes", nargs="+")
    parser.add_argument("--override", action="store_true")
    args = parser.parse_args()

    # Try different possible config locations
    possible_cfg_dirs = [
        module_root / "configs" / "data-processor",
        module_root / "magistracy-diplom-iu12" / "configs" / "data-processor",
        Path("/app/configs/data-processor")
    ]
    
    cfg_dir = None
    for d in possible_cfg_dirs:
        if d.exists():
            cfg_dir = d
            break
            
    if not cfg_dir:
        logger.error(f"Could not find config directory. Tried: {possible_cfg_dirs}")
        sys.exit(1)

    bboxes_cfg = load_yml(cfg_dir / "bboxes.yaml")
    overpass_cfg = load_yml(cfg_dir / "overpass.yaml")
    
    db_cfg = {
        'host': os.environ.get('APP__DB__HOST', 'localhost'),
        'port': int(os.environ.get('APP__DB__PORT', 5432)),
        'user': os.environ.get('APP__DB__USER', 'postgres'),
        'password': os.environ.get('APP__DB__PASSWORD', 'postgres'),
        'database': os.environ.get('APP__DB__NAME', 'nav_mas')
    }

    downloader = OSMDirectDownloader(db_cfg, overpass_cfg, bboxes_cfg, override=args.override)
    await downloader.connect_db()
    try:
        await downloader.download_all(args.bboxes)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
    finally:
        await downloader.close_db()

if __name__ == "__main__":
    asyncio.run(main())
