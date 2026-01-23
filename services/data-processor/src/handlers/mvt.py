"""
MVT Handler - generates Mapbox Vector Tiles on-the-fly.

Responsibilities:
- Generate MVT tiles from osm.ways table
- Handle tile coordinate conversion
- Return Protocol Buffer format
"""

from typing import Optional
from loguru import logger

from ..db.pool import DatabasePool
from ..db.queries import OSMQueries


import yaml
from pathlib import Path

class MVTHandler:
    """Handles MVT tile generation."""
    
    def __init__(self, db: DatabasePool):
        self.db = db
        self.lod_config = self._load_lod_config()
        
    def _load_lod_config(self) -> dict:
        """Load LOD configuration."""
        try:
            # Try loading from common config location or default
            config_path = Path("/app/configs/data-processor/mvt_style.yaml")
            if config_path.exists():
                with open(config_path) as f:
                    cfg = yaml.safe_load(f)
                    logger.info("Loaded MVT LOD config")
                    return cfg.get("lod", {})
            else:
                logger.warning("mvt_style.yaml not found, using defaults")
                return {}
        except Exception as e:
            logger.error(f"Failed to load MVT config: {e}")
            return {}

    def _get_visible_types(self, z: int) -> list:
        """Get list of visible highway types for zoom level."""
        # Find the specific level or the closest lower level key
        # Keys in yaml are integers
        
        # If config is empty or broken, fallback to safe defaults (City view)
        if not self.lod_config:
            if z >= 14: return ["ALL"]
            return ["motorway", "trunk", "primary"] # fallback

        # Check exact match
        if z in self.lod_config:
            types = self.lod_config[z]
            if "*" in types or "ALL" in types: return ["ALL"]
            return types

        # Find closest lower
        available_levels = sorted([k for k in self.lod_config.keys() if isinstance(k, int)])
        # filter those <= z
        lower = [l for l in available_levels if l <= z]
        
        if not lower:
            # Zoom is lower than lowest defined (e.g. z=-1?), unlikely
            # Return lowest defined
            if available_levels:
                types = self.lod_config[available_levels[0]]
                if "*" in types: return ["ALL"]
                return types
            return ["motorway", "trunk"] # default default

        target_level = lower[-1] # max of lower
        types = self.lod_config[target_level]
        if "*" in types: return ["ALL"]
        return types

    async def generate_tile(
        self,
        z: int,
        x: int,
        y: int
    ) -> Optional[bytes]:
        """
        Generate MVT tile for given coordinates.
        
        Args:
            z: Zoom level
            x: Tile X coordinate
            y: Tile Y coordinate
        
        Returns:
            MVT protobuf bytes or None if empty
        """
        try:
            visible_types = self._get_visible_types(z)
            
            async with self.db.acquire() as conn:
                mvt_data = await conn.fetchval(
                    OSMQueries.GENERATE_MVT_TILE,
                    z, x, y,
                    visible_types
                )
            
            if not mvt_data or len(mvt_data) == 0:
                # logger.trace(f"MVT tile [{z}/{x}/{y}] is empty")
                return None
            
            # logger.trace(
            #    f"MVT tile [{z}/{x}/{y}] generated: "
            #    f"{len(mvt_data)} bytes"
            # )
            
            return mvt_data
            
        except Exception as e:
            logger.error(f"MVT generation failed [{z}/{x}/{y}]: {e}")
            raise
