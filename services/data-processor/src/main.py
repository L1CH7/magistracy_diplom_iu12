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

from services.common.utils.loguru_config import configure_loguru

# Import components
from src.db.pool import DatabasePool
from src.state.task_manager import TaskManager
from src.handlers.tile_download import TileDownloadHandler
from src.handlers.mvt import MVTHandler
from src.api import status, tiles, debug, websocket


# ==================== Configuration ====================
# Using services.common.config.Settings
from services.common.config import load_settings, Settings



# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    # Initialize components
    logger.info("Initializing data-processor components...")
    
    settings = load_settings()
    
    # Load specialized configs
    from services.common.config import config_loader
    try:
        overpass_config = config_loader.load('data-processor/overpass.yaml')
    except Exception as e:
        logger.warning(f"Failed to load overpass.yaml: {e}. Using defaults.")
        overpass_config = {}

    # Settings from Env > Config File
    # If Env var set (Settings), usage is ambiguous if default is hardcoded in Settings.
    # Logic: Use Settings if non-default (meaning set by Env), else check Config File, else Default.
    # Since Settings are Pydantic with defaults, hard to know if user set them or default.
    # Generally Env > File > Default.
    # But here simple approach: Use Settings values (which come from Env or Defaults).
    # IF we want file to be source of domain config logic:
    
    tile_size = settings.data_processor_config.tile_size
    cpu_cores = settings.data_processor_config.cpu_cores
    
    # Check overpass.yaml for tile_size if setting is default (0.05) or maybe we prefer file?
    # User said "add them to config".
    # Let's override if file has them and Env didn't change (how to check? hard).
    # Let's prefer Env (Settings) but if they are defaults, maybe use file?
    # Actually, let's just use values from overpass.yaml if present, as that's the domain config.
    # Env vars usually override everything.
    # Use: Env > File > Default
    
    # If Env var NOT present, Settings has default.
    # If File present, it has distinct value.
    # We will assume Settings.tile_size is valid source. 
    # BUT, if we want to respect the file edits I just made:
    
    file_tile_size = overpass_config.get('tile_size') or overpass_config.get('tile_size_degrees')
    if file_tile_size is not None:
        # If settings is default, maybe use file? 
        # Safer: Just use file value if loaded, assuming Envs are for infrastructure mainly.
        # OR: overwrite settings with file value? context-dependent.
        # Given user request "add to config file", I will prioritize file config for these domain params.
        tile_size = float(file_tile_size)

    file_cpu_cores = overpass_config.get('cpu_cores')
    if file_cpu_cores is not None:
         cpu_cores = int(file_cpu_cores)
         
    from services.common.utils.loguru_config import setup_uvicorn_logging
    setup_uvicorn_logging()
         
    # 1. Database pool
    app.state.db = DatabasePool(
        host=settings.db.host,
        port=settings.db.port,
        database=settings.db.name,
        user=settings.db.user,
        password=settings.db.password
    )
    await app.state.db.connect()
    
    # 2. Task manager
    app.state.task_manager = TaskManager()
    
    # 3. Handlers
    app.state.tile_handler = TileDownloadHandler(
        db=app.state.db,
        task_manager=app.state.task_manager,
        overpass_servers=overpass_config.get("primary_servers", []) + overpass_config.get("fallback_servers", []),
        timeout=overpass_config.get("timeout", 300),
        tile_size=tile_size,
        cpu_cores=cpu_cores
    )
    
    app.state.mvt_handler = MVTHandler(db=app.state.db)
    
    # 4. Initialize API routers
    await status.init_status_api(
        app.state.db,
        app.state.task_manager
    )
    await tiles.init_tiles_api(
        app.state.tile_handler,
        app.state.mvt_handler
    )
    
    # 5. Recovery mechanism (find stuck tiles)
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
configure_loguru(service_name="data-processor", log_level="TRACE")

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
