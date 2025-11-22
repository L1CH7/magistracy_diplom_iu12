"""
Debug API - debug configuration and utilities.

Endpoints:
- GET /api/v1/debug/config - get debug configuration
"""

from fastapi import APIRouter
from loguru import logger
import yaml
import os
from typing import List


router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/config")
async def get_debug_config():
    """
    Get debug configuration.
    
    Returns grid tile size and download bounds.
    """
    # Загружаем bbox из конфига
    # В docker контейнере конфиги монтируются в /app/configs
    bboxes_path = '/app/configs/data-processor/bboxes.yaml'
    if not os.path.exists(bboxes_path):
        # Локальный режим - относительный путь
        bboxes_path = os.path.join(
            os.path.dirname(__file__),
            '../../../../configs/data-processor/bboxes.yaml'
        )
    
    with open(bboxes_path, 'r') as f:
        bboxes_config = yaml.safe_load(f)
    
    default_bbox_name = bboxes_config.get('default', 'moscow_mkad')
    bbox_data = bboxes_config.get(default_bbox_name, {})
    bbox_coords = bbox_data.get('coords', [37.30, 55.45, 37.90, 56.00])
    
    # Загружаем tile_size_degrees из overpass.yaml
    overpass_path = '/app/configs/data-processor/overpass.yaml'
    if not os.path.exists(overpass_path):
        overpass_path = os.path.join(
            os.path.dirname(__file__),
            '../../../../configs/data-processor/overpass.yaml'
        )
    
    with open(overpass_path, 'r') as f:
        overpass_config = yaml.safe_load(f)
    
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
