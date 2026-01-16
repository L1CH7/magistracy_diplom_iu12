"""
Tiles API - tile management endpoints.

Endpoints:
- POST /api/v1/tiles/download - download single tile
- POST /api/v1/tiles/redownload?west=...&south=...&east=...&north=...
        - force redownload bbox area
- GET /api/v1/tiles/{z}/{x}/{y}.mvt - get MVT tile
"""

import asyncio
import gzip
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response as FastAPIResponse
from loguru import logger

from ..handlers.tile_download import TileDownloadHandler
from ..handlers.mvt import MVTHandler


router = APIRouter(prefix="/api/v1/tiles", tags=["tiles"])


async def init_tiles_api(
    tile_handler: TileDownloadHandler,
    mvt_handler: MVTHandler
):
    """Initialize tiles API with handlers."""
    router.tile_handler = tile_handler
    router.mvt_handler = mvt_handler


def _clip_bbox_to_default(
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
            "original_bbox": (west, south, east, north) or None
        }
    
    Raises:
        HTTPException: If no intersection or invalid config
    """
    from fastapi import HTTPException
    from services.common.utils.config_loader import config_loader
    
    # Load default_bbox from bboxes.yaml
    bboxes_config = config_loader.load('data-processor/bboxes.yaml')
    
    default_bbox_name = bboxes_config.get('default', 'moscow_mkad')
    bbox_data = bboxes_config.get(default_bbox_name, {})
    default_coords = bbox_data.get('coords')
    
    if not default_coords or len(default_coords) != 4:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid default bbox config: {default_bbox_name}"
        )
    
    # default_bbox = (west, south, east, north)
    def_west, def_south, def_east, def_north = default_coords
    
    # Compute intersection: requested ∩ default_bbox
    clipped_west = max(west, def_west)
    clipped_south = max(south, def_south)
    clipped_east = min(east, def_east)
    clipped_north = min(north, def_north)
    
    # Check if intersection is valid (non-empty)
    if clipped_west >= clipped_east or clipped_south >= clipped_north:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested bbox does not intersect default_bbox "
                f"({default_bbox_name}): "
                f"[{def_west}, {def_south}, {def_east}, {def_north}]"
            )
        )
    
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
        "original_bbox": (west, south, east, north) if was_clipped else None
    }


@router.post("/download")
async def download_tile(lon: float, lat: float, bbox_size: float = 0.2):
    """
    Start tile download in background.
    
    CLIPS requested bbox to default_bbox from bboxes.yaml config.
    Only downloads intersection (requested ∩ default_bbox).
    
    Args:
        lon: Tile longitude (SW corner)
        lat: Tile latitude (SW corner)
        bbox_size: Tile size in degrees (default 0.2)
    
    Returns:
        {"status": "started", "tile_key": "...", "bbox": {...}, "clipped": bool}
    """
    # Compute initial bbox
    west, south = lon, lat
    east, north = lon + bbox_size, lat + bbox_size
    
    # Clip to default_bbox
    clip_result = _clip_bbox_to_default(west, south, east, north)
    clipped_bbox = clip_result["clipped_bbox"]
    was_clipped = clip_result["was_clipped"]
    
    # Use clipped bbox for download
    tile_key = (clipped_bbox[0], clipped_bbox[1])
    
    # Start download in background
    asyncio.create_task(
        router.tile_handler.download_tile(tile_key, clipped_bbox)
    )
    
    result = {
        "status": "started",
        "tile_key": f"{clipped_bbox[0]:.2f}_{clipped_bbox[1]:.2f}",
        "bbox": {
            "west": clipped_bbox[0],
            "south": clipped_bbox[1],
            "east": clipped_bbox[2],
            "north": clipped_bbox[3]
        },
        "clipped": was_clipped
    }
    
    if was_clipped:
        result["original_bbox"] = {
            "west": west,
            "south": south,
            "east": east,
            "north": north
        }
        result["message"] = (
            f"Bbox clipped to {clip_result['default_bbox_name']} "
            f"{clip_result['default_coords']}"
        )
    
    return result


@router.post("/redownload")
async def redownload_bbox(
    west: float,
    south: float,
    east: float,
    north: float
):
    """
    Force redownload of specific bbox area.
    
    CLIPS requested bbox to default_bbox from bboxes.yaml config.
    Only downloads intersection (requested ∩ default_bbox).
    
    Uses same _clip_bbox_to_default() logic as /download endpoint.
    
    Args:
        west: Western longitude boundary
        south: Southern latitude boundary
        east: Eastern longitude boundary
        north: Northern latitude boundary
    
    Returns:
        {"status": "redownload_started", "bbox": {...}, "clipped": bool}
    """
    # Clip to default_bbox (same logic as /download)
    clip_result = _clip_bbox_to_default(west, south, east, north)
    clipped_bbox = clip_result["clipped_bbox"]
    was_clipped = clip_result["was_clipped"]
    
    # Use clipped bbox for download
    tile_key = (clipped_bbox[0], clipped_bbox[1])
    
    # Запускаем загрузку (same as /download)
    asyncio.create_task(
        router.tile_handler.download_tile(tile_key, clipped_bbox)
    )
    
    result = {
        "status": "redownload_started",
        "bbox": {
            "west": clipped_bbox[0],
            "south": clipped_bbox[1],
            "east": clipped_bbox[2],
            "north": clipped_bbox[3]
        },
        "clipped": was_clipped
    }
    
    if was_clipped:
        result["original_bbox"] = {
            "west": west,
            "south": south,
            "east": east,
            "north": north
        }
        result["message"] = (
            f"Bbox clipped to {clip_result['default_bbox_name']} "
            f"{clip_result['default_coords']}"
        )
    
    return result


@router.get("/{z}/{x}/{y}.mvt")
async def get_mvt_tile(z: int, x: int, y: int):
    """
    Get Mapbox Vector Tile.
    
    Args:
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
    
    Returns:
        MVT protobuf data
    """
    # Validate tile coordinates
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom level")
    
    max_tile = 2 ** z
    if x < 0 or x >= max_tile or y < 0 or y >= max_tile:
        raise HTTPException(status_code=400, detail="Invalid tile coords")
    
    try:
        mvt_data = await router.mvt_handler.generate_tile(z, x, y)
        
        if not mvt_data:
            # 204 No Content - valid but empty tile
            return FastAPIResponse(
                content=b"",
                status_code=204,
                headers={"Cache-Control": "public, max-age=3600"}
            )
        
        # Compress MVT data with gzip
        compressed_data = gzip.compress(mvt_data, compresslevel=6)
        
        return Response(
            content=compressed_data,
            media_type="application/x-protobuf",
            headers={
                "Content-Encoding": "gzip",
                "Cache-Control": "public, max-age=604800",  # 7 days
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        logger.error(f"MVT tile [{z}/{x}/{y}] failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate tile: {str(e)}"
        )
