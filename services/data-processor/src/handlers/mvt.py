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




class MVTHandler:
    """Handles MVT tile generation."""
    
    def __init__(self, db: DatabasePool):
        self.db = db
        # Start matching strict empty state (will be populated by client)
        self.lod_config = []

    def update_lod_config(self, new_config: dict):
        """Update LOD configuration at runtime."""
        if not new_config:
            return
        
        # Store config as raw list of layers for range checking
        # Format: [{'minzoom': 0, 'maxzoom': 5, 'highways': [...]}, ...]
        try:
            if "layers" in new_config:
                self.lod_config = new_config["layers"]
                logger.info(f"Updated LOD config (layers mode): {len(self.lod_config)} layers")
            else:
                # Direct update not supported in this strict mode? 
                # Let's assume new_config IS the layers list if it's a list
                if isinstance(new_config, list):
                    self.lod_config = new_config
                    logger.info(f"Updated LOD config (list mode): {len(self.lod_config)} layers")
                else:
                    logger.warning("Invalid LOD config format received (expected 'layers' key or list)")
                
        except Exception as e:
            logger.error(f"Failed to update LOD config: {e}")

    def _get_visible_types(self, z: int) -> list:
        """Get list of visible highway types for zoom level."""
        # Strict range check: minzoom <= z < maxzoom
        
        # If config is empty, fallback to safe defaults
        if not self.lod_config or not isinstance(self.lod_config, list):
            # Fallback hardcoded logic if no config yet (e.g. before client connects)
            if z >= 14: return ["ALL"]
            if z >= 10: return ["motorway", "trunk", "primary", "secondary", "tertiary"]
            return ["motorway", "trunk", "primary"]

        # Iterate layers
        for layer in self.lod_config:
            min_z = layer.get("minzoom", 0)
            max_z = layer.get("maxzoom", 25) # Default max if not set
            
            # Check range
            if min_z <= z < max_z:
                highways = layer.get("highways", [])
                # If highways list is empty, it means "show nothing" for this layer?
                # Or if it contains specific types, use them.
                return highways
        
        # If no range matches (e.g. z < 0 or z > max defined), return valid default
        # For z > max, usually we want highest detail
        # But per user request "strict simple logic", if not found, maybe empty?
        # Let's fallback to the last layer if z >= all maxzooms
        if self.lod_config:
             # Sort by minzoom
             last_layer = sorted(self.lod_config, key=lambda x: x.get("minzoom", 0))[-1]
             if z >= last_layer.get("maxzoom", 100):
                 return last_layer.get("highways", [])

        return ["motorway", "trunk"] # Absolute fallback

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
