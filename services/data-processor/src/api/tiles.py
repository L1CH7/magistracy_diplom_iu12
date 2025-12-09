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
import math
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


def tile_zxy_to_bbox(z: int, x: int, y: int) -> tuple:
    """
    Convert MVT tile coordinates (z/x/y) to geographic bbox.
    
    Uses Web Mercator projection formulas.
    
    Args:
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
    
    Returns:
        (west, south, east, north) in WGS84 degrees
    """
    n = 2.0 ** z
    
    # West longitude
    west = x / n * 360.0 - 180.0
    
    # East longitude
    east = (x + 1) / n * 360.0 - 180.0
    
    # North latitude
    lat_rad_north = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    north = math.degrees(lat_rad_north)
    
    # South latitude
    lat_rad_south = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
    south = math.degrees(lat_rad_south)
    
    return (west, south, east, north)


async def _check_tile_data_exists(
    bbox: tuple
) -> bool:
    """
    Check if OSM data exists for given bbox in osm.cached_tiles.
    
    Queries database to verify if area has been downloaded.
    
    Args:
        bbox: (west, south, east, north) in WGS84 degrees
    
    Returns:
        True if data downloaded (status='complete'), False otherwise
    """
    west, south, east, north = bbox
    
    # Get database pool from router
    db = router.tile_handler.db
    
    async with db.acquire() as conn:
        # Check if bbox intersects any complete cached tiles
        query = """
            SELECT EXISTS(
                SELECT 1
                FROM osm.cached_tiles
                WHERE download_status = 'complete'
                  AND ST_Intersects(
                      bbox,
                      ST_MakeEnvelope($1, $2, $3, $4, 4326)
                  )
            )
        """
        
        result = await conn.fetchval(query, west, south, east, north)
        return result


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
    from src.utils.config_loader import config_loader
    
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
    Get Mapbox Vector Tile with auto-download.
    
    Workflow:
    1. Convert z/x/y to geographic bbox
    2. Check if OSM data exists in osm.cached_tiles
    3. If no data:
       - Check if bbox within default_bbox → 202 + trigger download
       - If outside default_bbox → 204 (no content)
    4. If data exists → generate and return MVT tile
    
    Args:
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
    
    Returns:
        - 200: MVT protobuf data (gzipped)
        - 202: Accepted (download started)
        - 204: No content (tile outside default_bbox or empty)
        - 400: Invalid coordinates
        - 500: Internal error
    """
    # Validate tile coordinates
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom level")
    
    max_tile = 2 ** z
    if x < 0 or x >= max_tile or y < 0 or y >= max_tile:
        raise HTTPException(status_code=400, detail="Invalid tile coords")
    
    try:
        # Convert tile coords to geographic bbox
        tile_bbox = tile_zxy_to_bbox(z, x, y)
        west, south, east, north = tile_bbox
        
        # Check if OSM data exists for this tile
        data_exists = await _check_tile_data_exists(tile_bbox)
        
        if not data_exists:
            # No data - check if within default_bbox and trigger download
            logger.info(
                f"MVT tile [{z}/{x}/{y}] no data, checking default_bbox"
            )
            
            try:
                # Try to clip to default_bbox
                clip_result = _clip_bbox_to_default(west, south, east, north)
                clipped_bbox = clip_result["clipped_bbox"]
                
                # Start background download (same as POST /download)
                tile_key = (clipped_bbox[0], clipped_bbox[1])
                asyncio.create_task(
                    router.tile_handler.download_tile(tile_key, clipped_bbox)
                )
                
                logger.info(
                    f"MVT tile [{z}/{x}/{y}] download started: "
                    f"bbox={clipped_bbox}"
                )
                
                # Return 202 Accepted
                return Response(
                    status_code=202,
                    content=b"",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Download-Status": "started"
                    }
                )
                
            except HTTPException as clip_error:
                # Tile outside default_bbox → 204 No Content
                logger.debug(
                    f"MVT tile [{z}/{x}/{y}] outside default_bbox: "
                    f"{clip_error.detail}"
                )
                return FastAPIResponse(
                    content=b"",
                    status_code=204,
                    headers={"Cache-Control": "public, max-age=3600"}
                )
        
        # Data exists - generate MVT tile
        mvt_data = await router.mvt_handler.generate_tile(z, x, y)
        
        if not mvt_data:
            # Data exists but tile empty (no ways in this exact tile)
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MVT tile [{z}/{x}/{y}] failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate tile: {str(e)}"
        )
