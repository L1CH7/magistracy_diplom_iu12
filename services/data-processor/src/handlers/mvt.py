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
            async with self.db.acquire() as conn:
                mvt_data = await conn.fetchval(
                    OSMQueries.GENERATE_MVT_TILE,
                    z, x, y
                )
            
            if not mvt_data or len(mvt_data) == 0:
                logger.trace(f"MVT tile [{z}/{x}/{y}] is empty")
                return None
            
            logger.trace(
                f"MVT tile [{z}/{x}/{y}] generated: "
                f"{len(mvt_data)} bytes"
            )
            
            return mvt_data
            
        except Exception as e:
            logger.error(f"MVT generation failed [{z}/{x}/{y}]: {e}")
            raise
