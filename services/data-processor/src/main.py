"""
Data Processor Service - refactored architecture.

Clean separation:
- handlers/ - business logic
- state/ - task tracking
- db/ - database operations
- api/ - HTTP endpoints (thin layer)
"""

import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Add project root to path (need src.* imports)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.loguru_config import configure_loguru

# Import components
from src.db.pool import DatabasePool
from src.state.task_manager import TaskManager
from src.handlers.tile_download import TileDownloadHandler
from src.handlers.mvt import MVTHandler
from src.api import status, tiles, debug, websocket


# ==================== Configuration ====================

def load_config() -> dict:
    """Load configuration from environment."""
    return {
        "db": {
            "host": os.getenv("DB_HOST", "postgis"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "database": os.getenv("DB_NAME", "osm"),
            "user": os.getenv("DB_USER", "diplom"),
            "password": os.getenv("DB_PASSWORD", "diplom_pass"),
        },
        "overpass": {
            "servers": [
                "https://overpass-api.de",
                "https://overpass.kumi.systems",
                "https://overpass.openstreetmap.ru"
            ],
            "timeout": 300
        }
    }


# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    config = load_config()
    
    # Initialize components
    logger.info("Initializing data-processor components...")
    
    # 1. Database pool
    app.state.db = DatabasePool(**config["db"])
    await app.state.db.connect()
    
    # 2. Task manager
    app.state.task_manager = TaskManager()
    
    # 3. Handlers
    app.state.tile_handler = TileDownloadHandler(
        db=app.state.db,
        task_manager=app.state.task_manager,
        overpass_servers=config["overpass"]["servers"],
        timeout=config["overpass"]["timeout"]
    )
    
    app.state.mvt_handler = MVTHandler(db=app.state.db)
    
    # 5. Initialize API routers
    await status.init_status_api(
        app.state.db,
        app.state.task_manager
    )
    await tiles.init_tiles_api(
        app.state.tile_handler,
        app.state.mvt_handler
    )
    
    # 6. Recovery mechanism (find stuck tiles)
    await recover_failed_downloads(app.state.db, app.state.task_manager)
    
    logger.success("Data-processor initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down data-processor...")
    await app.state.db.close()
    logger.info("Data-processor stopped")


async def recover_failed_downloads(
    db: DatabasePool,
    task_manager: TaskManager
):
    """
    Recover stuck downloads on startup.
    
    Finds tiles stuck in 'downloading' state and marks them as failed.
    """
    from src.db.queries import OSMQueries
    
    async with db.acquire() as conn:
        stuck_tiles = await conn.fetch(OSMQueries.FIND_STUCK_TILES)
    
    if not stuck_tiles:
        logger.info("No stuck tiles found")
        return
    
    logger.warning(f"Found {len(stuck_tiles)} stuck tiles, resetting...")
    
    async with db.acquire() as conn:
        for row in stuck_tiles:
            await conn.execute(
                OSMQueries.RESET_STUCK_TILE,
                row["tile_key"]
            )
            logger.info(f"Reset stuck tile: {row['tile_key']}")
    
    logger.success(f"Recovered {len(stuck_tiles)} stuck tiles")


# ==================== FastAPI App ====================

# Configure logging
configure_loguru()

# Create app
app = FastAPI(
    title="Data Processor Service",
    description="OSM data management and MVT generation",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount routers
app.include_router(status.router)
app.include_router(websocket.router)
app.include_router(tiles.router)
app.include_router(debug.router)


# ==================== Health Check ====================

@app.get("/health")
async def health_check():
    """Service health check."""
    try:
        async with app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy",
            "service": "data-processor",
            "database": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "data-processor",
            "database": "disconnected",
            "error": str(e)
        }


# ==================== Root ====================

@app.get("/")
async def root():
    """Service info."""
    return {
        "service": "data-processor",
        "version": "2.0.0",
        "description": "OSM data management and MVT generation",
        "endpoints": {
            "status": "/api/v1/status",
            "tasks": "/api/v1/tasks",
            "download": "POST /api/v1/tiles/download",
            "mvt": "/api/v1/tiles/{z}/{x}/{y}.mvt",
            "websocket": "/ws/data_updates",
            "health": "/health"
        }
    }
