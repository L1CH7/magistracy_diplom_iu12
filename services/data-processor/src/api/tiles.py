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
    from services.common.config import config_loader
    
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
@router.post("/download/")
async def download_tile(
    lon: float = None, 
    lat: float = None, 
    bbox_size: float = 0.2,
    bbox: str = None # Format: "west,south,east,north"
):
    """
    Start tile/area download in background.
    
    If no arguments provided, downloads default_bbox.
    If arguments provided, clips to default_bbox.
    
    Args:
        lon: Tile longitude (SW corner) - Optional
        lat: Tile latitude (SW corner) - Optional
        bbox_size: Size in degrees - Optional
        bbox: "west,south,east,north" string - Optional
    """
    # Determine requested bbox
    if bbox:
        try:
            west, south, east, north = map(float, bbox.split(','))
        except ValueError:
             raise HTTPException(status_code=400, detail="Invalid bbox format. Use 'west,south,east,north'")
    elif lon is not None and lat is not None:
        west, south = lon, lat
        east, north = lon + bbox_size, lat + bbox_size
    else:
        # No args = use full default_bbox
        # We can pass very large bbox that covers everything, clip will handle it.
        west, south, east, north = -180, -90, 180, 90 
    
    # Clip to default_bbox
    clip_result = _clip_bbox_to_default(west, south, east, north)
    clipped_bbox = clip_result["clipped_bbox"]
    was_clipped = clip_result["was_clipped"]
    
    # Start download in background
    # Note: We don't await the whole download here, just the start
    # But download_area is async and runs potentially long.
    # We should wrap it in create_task.
    asyncio.create_task(
        router.tile_handler.download_area(clipped_bbox, overwrite=True)
    )
    
    result = {
        "status": "started",
        "bbox": {
            "west": clipped_bbox[0],
            "south": clipped_bbox[1],
            "east": clipped_bbox[2],
            "north": clipped_bbox[3]
        },
        "message": "Download started in background"
    }
    
    if was_clipped:
        result["original_bbox"] = {
            "west": west,
            "south": south,
            "east": east,
            "north": north
        }
        result["clip_info"] = (
            f"Bbox clipped to {clip_result['default_bbox_name']} "
            f"{clip_result['default_coords']}"
        )
    
    return result


@router.post("/download/stop")
async def stop_downloads():
    """Stop all active downloads."""
    await router.tile_handler.cancel_all_downloads()
    return {"status": "stopped", "message": "All download tasks cancelled"}


@router.get("/{z}/{x}/{y}.mvt")
async def get_mvt_tile(z: int, x: int, y: int):
    """
    Get Mapbox Vector Tile.
    
    If tile missing but in default_bbox, triggers download.
    """
    # Validate tile coordinates
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom level")
    
    max_tile = 2 ** z
    if x < 0 or x >= max_tile or y < 0 or y >= max_tile:
        raise HTTPException(status_code=400, detail="Invalid tile coords")
    
    # 1. Check intersection with default_bbox
    # We need tile_to_bbox and crop_default_bbox
    from ..handlers.utils import tile_to_bbox, crop_default_bbox
    
    tile_bbox = tile_to_bbox(z, x, y)
    clip_result = crop_default_bbox(*tile_bbox)
    
    if not clip_result["is_valid"]:
        # Tile is completely outside default_bbox
        return FastAPIResponse(status_code=204)

    try:
        mvt_data = await router.mvt_handler.generate_tile(z, x, y)
        
        if not mvt_data or len(mvt_data) < 100:
            # Check if we already have this area downloaded (valid empty tile)
            try:
                w, s, e, n = tile_bbox
                async with router.tile_handler.db.acquire() as conn:
                    is_covered = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT 1 FROM osm.cached_tiles 
                            WHERE download_status = 'complete'
                            AND ST_Covers(bbox, ST_MakeEnvelope($1, $2, $3, $4, 4326))
                        )
                    """, w, s, e, n)
                    
                    if is_covered:
                        # It's a valid empty area (e.g., forest/water without roads)
                        return FastAPIResponse(
                            content=b"",
                            # user logs showed 200 OK for empty tiles in some cases.
                            status_code=200,
                            headers={"Cache-Control": "public, max-age=3600"}
                        )
            except Exception as e:
                logger.warning(f"Failed to check coverage: {e}")

            # Data missing -> 202 Accepted + Trigger Download
            target_bbox = clip_result["clipped_bbox"] # Should be tile_bbox clipped to default
            
            asyncio.create_task(
                router.tile_handler.download_area(target_bbox, overwrite=False)
            )
            
            return FastAPIResponse(
                status_code=202,
                content=b"",
                headers={"Retry-After": "5"}
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
