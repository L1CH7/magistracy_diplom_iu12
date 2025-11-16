"""
Data Processor Service - OSM data fetching and graph construction.

Responsibilities:
- Fetch OSM data (Overpass API)
- Build road graph (nodes, edges)
- Calculate bearings (azimuth)
- Calculate capacity (by speed_limit and mode)
- Pre-compute geom_3857 for MVT tiles
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Add project root to path for src imports
root_path = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(root_path))
from src.utils.loguru_config import configure_loguru

configure_loguru(service_name="data-processor")

# WebSocket clients registry
ws_clients: set[WebSocket] = set()


from .manager import DataProcessorManager  # noqa: E402
from .models import (  # noqa: E402
    FetchDataRequest,
    FetchDataResponse,
    ProcessGraphRequest,
    ProcessGraphResponse
)


# Global manager
data_manager: DataProcessorManager = None


async def broadcast_to_websockets(message: dict):
    """Broadcast message to all connected WebSocket clients."""
    if not ws_clients:
        return
    
    import json
    message_json = json.dumps(message)
    
    # Send to all clients (remove disconnected on failure)
    disconnected = []
    for client in ws_clients:
        try:
            await client.send_text(message_json)
        except Exception:
            disconnected.append(client)
    
    # Clean up disconnected clients
    for client in disconnected:
        ws_clients.discard(client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global data_manager
    
    logger.info("Starting Data Processor Service...")
    
    # Initialize manager
    data_manager = DataProcessorManager()
    await data_manager.initialize()
    
    # Register WebSocket notification callback
    data_manager.set_ws_notify_callback(broadcast_to_websockets)
    
    logger.success("Data Processor Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Data Processor Service...")
    await data_manager.shutdown()
    logger.success("Data Processor Service stopped")


app = FastAPI(
    title="Data Processor Service",
    description="OSM data fetching and graph construction",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for GUI access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "data-processor"
    }


@app.post("/api/v1/data/fetch", response_model=FetchDataResponse)
async def fetch_osm_data(
    request: FetchDataRequest,
    background_tasks: BackgroundTasks
):
    """
    Fetch OSM data for bounding box.
    
    Uses Overpass API.
    Returns job_id, runs in background.
    """
    job_id = await data_manager.start_fetch_job(
        bbox=request.bbox,
        highway_types=request.highway_types
    )
    
    # Run in background
    background_tasks.add_task(
        data_manager.run_fetch_job,
        job_id
    )
    
    return FetchDataResponse(
        job_id=job_id,
        status="started"
    )


@app.get("/api/v1/data/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get fetch job status."""
    status = await data_manager.get_job_status(job_id)
    
    return status


@app.post("/api/v1/graph/process", response_model=ProcessGraphResponse)
async def process_graph(
    request: ProcessGraphRequest,
    background_tasks: BackgroundTasks
):
    """
    Process raw OSM data into graph.
    
    Steps:
    1. Build nodes and edges
    2. Calculate bearings
    3. Calculate capacity
    4. Pre-compute geom_3857
    5. Create spatial indexes
    
    Returns job_id, runs in background.
    """
    job_id = await data_manager.start_process_job(
        osm_data_path=request.osm_data_path,
        capacity_mode=request.capacity_mode
    )
    
    # Run in background
    background_tasks.add_task(
        data_manager.run_process_job,
        job_id
    )
    
    return ProcessGraphResponse(
        job_id=job_id,
        status="started"
    )


@app.get("/api/v1/graph/jobs/{job_id}")
async def get_process_job_status(job_id: str):
    """Get graph processing job status."""
    status = await data_manager.get_job_status(job_id)
    
    return status


@app.get("/api/v1/data/status")
async def get_global_status():
    """
    Получить глобальный статус Data Processor.
    
    Возвращает:
    - Количество активных скачиваний
    - Общее количество ways в БД
    - Список скачивающихся тайлов
    """
    status = await data_manager.get_global_status()
    return status


@app.get("/api/v1/data/tile/{lon}/{lat}")
async def check_tile_status(lon: float, lat: float):
    """
    Проверить наличие тайла в БД.
    
    Args:
        lon: Longitude
        lat: Latitude
    
    Возвращает статус тайла (есть в БД или нет).
    """
    tile_key = data_manager._coord_to_tile_key(lon, lat)
    status = await data_manager.check_tile_in_db(tile_key)
    
    return {
        "tile": {"lon": tile_key[0], "lat": tile_key[1]},
        "exists_in_db": status["exists"],
        "ways_count": status["ways_count"]
    }


@app.post("/api/v1/data/tile/{lon}/{lat}/ensure")
async def ensure_tile_available(lon: float, lat: float):
    """
    Ensure tile is present in database.
    
    If tile is missing - downloads and saves.
    If tile exists - returns status.
    
    Server-side validation: rejects tiles outside moscow_medium bounds.
    
    Returns:
        {"status": "exists|downloaded|error|rejected", "ways_count": int}
    """
    # Validate against default bbox from config
    bounds = data_manager.default_bbox
    
    if (lon < bounds["west"] or
            lon >= bounds["east"] or
            lat < bounds["south"] or
            lat >= bounds["north"]):
        
        logger.warning(
            f"Tile [{lon}, {lat}] REJECTED: outside default bounds "
            f"[{bounds['west']}-{bounds['east']}, "
            f"{bounds['south']}-{bounds['north']}]"
        )
        return {
            "status": "rejected",
            "reason": "Outside configured bounds",
            "bounds": bounds,
            "ways_count": 0
        }
    
    tile_key = data_manager._coord_to_tile_key(lon, lat)
    result = await data_manager.ensure_tile_downloaded(tile_key)
    
    return {
        "tile": {"lon": tile_key[0], "lat": tile_key[1]},
        **result
    }


@app.get("/api/v1/data/stats")
async def get_data_stats():
    """
    Get current OSM data statistics (way count, etc).
    Used by GUI to detect when new data is loaded.
    """
    ways_count = await data_manager.get_ways_count()
    return {
        "ways_count": ways_count,
        "status": "ok"
    }


@app.get("/api/v1/tiles/{z}/{x}/{y}.mvt")
async def get_mvt_tile(z: int, x: int, y: int):
    """
    Get Mapbox Vector Tile (MVT) for given tile coordinates.
    
    Returns:
      - 200 OK + data: Tile has roads, ready to display
      - 202 Accepted: Tile is downloading, no data yet (GUI will retry)
      - 204 No Content: Tile outside default bbox (e.g. America, Europe)
      - 500 on error
    
    Design:
    - 202/204 prevent caching, GUI retries on pan/zoom
    - 200 cached for 1 hour for performance
    """
    from fastapi.responses import Response
    
    logger.info(f"[MVT REQUEST] GUI requested tile [{z}/{x}/{y}]")
    result = await data_manager.get_mvt_tile(z, x, y)
    
    # Result: {"mvt": bytes, "status": "ready|downloading|outside"}
    status = result.get("status", "ready")
    mvt = result.get("mvt", b"")
    
    if status == "outside":
        # Tile outside default bbox - no data, will never have data
        logger.debug(
            f"MVT [{z}/{x}/{y}] outside bbox - returning 204 No Content"
        )
        return Response(
            status_code=204,
            content=b"",
            media_type="application/x-protobuf"
        )
    
    if status == "downloading":
        # Tile is being downloaded - no data yet, but will have soon
        logger.debug(
            f"MVT [{z}/{x}/{y}] downloading - returning 202 Accepted"
        )
        return Response(
            status_code=202,
            content=b"",
            media_type="application/x-protobuf"
        )
    
    if not mvt or len(mvt) == 0:
        # No data yet, not downloading - fallback to 204
        logger.debug(f"MVT [{z}/{x}/{y}] empty - returning 204 No Content")
        return Response(
            status_code=204,
            content=b"",
            media_type="application/x-protobuf"
        )
    
    # Tile has data - return with caching
    logger.debug(f"MVT [{z}/{x}/{y}] ready: {len(mvt)} bytes")
    return Response(
        content=mvt,
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )


@app.get("/api/v1/debug/config")
async def get_debug_config():
    """
    Get debug configuration for GUI visualization.
    
    Returns:
    {
        "default_bbox": {"west": ..., "south": ..., "east": ..., "north": ...},
        "tile_size_degrees": 0.05,
        "loaded_tiles": [[lon, lat], ...]  // Tiles currently in DB
    }
    """
    # Get tiles currently in DB (filtered by default_bbox)
    loaded_tiles = []
    bounds = data_manager.default_bbox
    tile_size = data_manager.tile_size_degrees
    async with data_manager.db_pool.acquire() as conn:
        # Query distinct tile keys (rounded to tile_size grid)
        # Filter by default_bbox to show only tiles within configured area
        rows = await conn.fetch("""
            SELECT DISTINCT
                FLOOR(ST_X(ST_Centroid(geom)) / $1) * $1 AS tile_lon,
                FLOOR(ST_Y(ST_Centroid(geom)) / $1) * $1 AS tile_lat
            FROM osm.ways
            WHERE ST_Intersects(
                geom,
                ST_MakeEnvelope($2, $3, $4, $5, 4326)
            )
            ORDER BY tile_lon, tile_lat
        """, tile_size, bounds["west"], bounds["south"],
             bounds["east"], bounds["north"])
        
        loaded_tiles = [
            [float(row['tile_lon']), float(row['tile_lat'])]
            for row in rows
        ]
    
    return {
        "default_bbox": data_manager.default_bbox,
        "tile_size_degrees": data_manager.tile_size_degrees,
        "loaded_tiles": loaded_tiles
    }


@app.websocket("/api/v1/ws/tile-updates")
async def websocket_tile_updates(websocket: WebSocket):
    """
    WebSocket endpoint for tile update notifications.
    
    GUI connects here to receive push notifications when tiles finish
    downloading.
    
    Message format:
    {
        "type": "tiles_ready",
        "tiles": [[z, x, y], ...]  // MVT tiles affected by OSM tile
    }
    """
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"[WS] GUI connected, total clients: {len(ws_clients)}")
    
    try:
        # Keep connection alive
        while True:
            # Wait for ping/pong to detect disconnect
            await websocket.receive_text()
    except Exception as e:
        logger.info(f"[WS] GUI disconnected: {e}")
    finally:
        ws_clients.remove(websocket)
        logger.info(
            f"[WS] GUI removed, remaining clients: {len(ws_clients)}"
        )

