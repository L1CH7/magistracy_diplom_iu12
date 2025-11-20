"""
Tiles API - tile management endpoints.

Endpoints:
- POST /api/v1/tiles/download - download single tile
- POST /api/v1/tiles/{tile_key}/redownload - force redownload
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


@router.post("/download")
async def download_tile(lon: float, lat: float, bbox_size: float = 0.2):
    """
    Start tile download in background.
    
    Args:
        lon: Tile longitude (SW corner)
        lat: Tile latitude (SW corner)
        bbox_size: Tile size in degrees (default 0.2)
    
    Returns:
        {"status": "started", "tile_key": "..."}
    """
    tile_key = (lon, lat)
    bbox = (lon, lat, lon + bbox_size, lat + bbox_size)
    
    # Start download in background
    asyncio.create_task(
        router.tile_handler.download_tile(tile_key, bbox)
    )
    
    return {
        "status": "started",
        "tile_key": f"{lon:.2f}_{lat:.2f}",
        "bbox": bbox
    }


@router.post("/{tile_key}/redownload")
async def redownload_tile(tile_key: str):
    """
    Force redownload of specific tile.
    
    Args:
        tile_key: Tile identifier (e.g. "37.60_55.75")
    
    Returns:
        {"status": "redownload_started"}
    """
    from ..db.queries import parse_tile_key, OSMQueries
    
    # Parse tile key
    tile_tuple = parse_tile_key(tile_key)
    if not tile_tuple:
        raise HTTPException(
            status_code=400,
            detail="Invalid tile_key format. Expected: 'lon_lat'"
        )
    
    # Reset tile status in DB
    async with router.tile_handler.db.acquire() as conn:
        result = await conn.fetchval(
            OSMQueries.RESET_TILE_FOR_REDOWNLOAD,
            tile_key
        )
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Tile {tile_key} not found"
            )
    
    # Start download
    lon, lat = tile_tuple
    bbox = (lon, lat, lon + 0.2, lat + 0.2)
    
    asyncio.create_task(
        router.tile_handler.download_tile(tile_tuple, bbox)
    )
    
    return {
        "status": "redownload_started",
        "tile_key": tile_key
    }


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
