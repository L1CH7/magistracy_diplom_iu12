"""
Utility functions for data processor.
"""

from typing import List, Tuple, Generator
import math

def split_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    tile_size: float
) -> Generator[Tuple[float, float, float, float], None, None]:
    """
    Split a bounding box into smaller tiles of given size.
    
    Args:
        west: Western longitude
        south: Southern latitude
        east: Eastern longitude
        north: Northern latitude
        tile_size: Size of square tile in degrees
        
    Yields:
        Tuple[float, float, float, float]: (tile_west, tile_south, tile_east, tile_north)
    """
    w = west
    while w < east:
        # Ensure we don't go past the eastern boundary
        curr_east = min(w + tile_size, east)
        
        s = south
        while s < north:
            # Ensure we don't go past the northern boundary
            curr_north = min(s + tile_size, north)
            
            yield (w, s, curr_east, curr_north)
            
            s += tile_size
            
        w += tile_size

def crop_default_bbox(
    west: float,
    south: float,
    east: float,
    north: float
) -> dict:
    """
    Clip requested bbox to default_bbox from bboxes.yaml.
    
    Returns intersection (requested ∩ default_bbox).
    
    Returns:
        {
            "clipped_bbox": (west, south, east, north),
            "was_clipped": bool,
            "default_bbox_name": str,
            "original_bbox": (west, south, east, north) or None,
            "is_valid": bool  # True if intersection is non-empty
        }
    """
    from services.common.config import config_loader
    from loguru import logger
    
    # Load default_bbox from bboxes.yaml
    bboxes_config = config_loader.load('data-processor/bboxes.yaml')
    
    default_bbox_name = bboxes_config.get('default', 'moscow_mkad')
    bbox_data = bboxes_config.get(default_bbox_name, {})
    default_coords = bbox_data.get('coords')
    
    if not default_coords or len(default_coords) != 4:
        logger.error(f"Invalid default bbox config: {default_bbox_name}")
        return {"is_valid": False}
    
    # default_bbox = (west, south, east, north)
    def_west, def_south, def_east, def_north = default_coords
    
    # Compute intersection: requested ∩ default_bbox
    clipped_west = max(west, def_west)
    clipped_south = max(south, def_south)
    clipped_east = min(east, def_east)
    clipped_north = min(north, def_north)
    
    # Check if intersection is valid (non-empty)
    if clipped_west >= clipped_east or clipped_south >= clipped_north:
         return {
             "is_valid": False,
             "clipped_bbox": None,
             "default_bbox_name": default_bbox_name,
             "default_coords": default_coords
         }
    
    # Check if bbox was clipped
    was_clipped = (
        clipped_west != west or clipped_south != south or
        clipped_east != east or clipped_north != north
    )
    
    return {
        "clipped_bbox": (clipped_west, clipped_south, clipped_east, clipped_north),
        "was_clipped": was_clipped,
        "default_bbox_name": default_bbox_name,
        "default_coords": default_coords,
        "original_bbox": (west, south, east, north) if was_clipped else None,
        "is_valid": True
    }

def tile_to_bbox(z: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """
    Convert tile coordinates to bounding box (West, South, East, North).
    Web Mercator scheme.
    """
    import math
    
    n = 2.0 ** z
    lon_deg = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    
    # Next tile
    lon_deg_next = (x + 1) / n * 360.0 - 180.0
    lat_rad_next = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    lat_deg_next = math.degrees(lat_rad_next)
    
    # BBox: West, South, East, North
    # Note: Y goes down in tile coords (0 is top), so lat_deg > lat_deg_next
    return (
        lon_deg,          # West
        lat_deg_next,     # South
        lon_deg_next,     # East
        lat_deg           # North
    )

