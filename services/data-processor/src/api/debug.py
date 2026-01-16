"""
Debug API - debug configuration and utilities.

Endpoints:
- GET /api/v1/debug/config - get debug configuration
"""

from fastapi import APIRouter
from loguru import logger
from typing import List
from services.common.utils.config_loader import config_loader


router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/config")
async def get_debug_config():
    """
    Get debug configuration.
    
    Returns grid tile size and download bounds.
    """
    # Load bboxes from config_loader
    bboxes_config = config_loader.load('data-processor/bboxes.yaml')
    
    default_bbox_name = bboxes_config.get('default', 'moscow_mkad')
    bbox_data = bboxes_config.get(default_bbox_name, {})
    bbox_coords = bbox_data.get('coords', [37.30, 55.45, 37.90, 56.00])
    
    # Load tile_size_degrees from overpass.yaml
    overpass_config = config_loader.load('data-processor/overpass.yaml')
    tile_size_degrees = overpass_config.get('tile_size_degrees', 0.05)
    
    config = {
        "tile_size_degrees": tile_size_degrees,
        "default_bbox": {
            "west": bbox_coords[0],
            "south": bbox_coords[1],
            "east": bbox_coords[2],
            "north": bbox_coords[3]
        },
        "bbox_border": {
            "color": "#00ffff",
            "width": 3,
            "dasharray": [4, 4],
            "opacity": 0.9
        },
        "grid": {
            "enabled": True,
            "color": "#000000",
            "width": 0.5,
            "opacity": 0.4
        },
        "loaded_tiles": {
            "fill_color": "#00ff00",
            "fill_opacity": 0.15,
            "border_color": "#00aa00",
            "border_width": 1,
            "border_opacity": 0.3
        }
    }
    
    tile_size_degrees = config['tile_size_degrees']
    logger.debug(f"Debug config requested: tile_size_degrees={tile_size_degrees}°")
    
    return config


@router.get("/loaded-tiles")
async def get_loaded_tiles() -> List[str]:
    """
    Get list of tile keys that have cached OSM data.
    
    Returns list of tile keys like ['37.30_55.45', '37.50_55.65', ...]
    """
    # TODO: Получить список тайлов из БД через dependency injection
    # Для тестирования вернём пустой список
    logger.debug("Loaded tiles requested (stub implementation)")
    return []


async def init_debug_api():
    """Initialize debug API (if needed for future config loading)."""
    pass
