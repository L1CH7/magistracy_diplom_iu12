"""
Router Service - manages routing graph and provides routing API.

Responsibilities:
- Build and maintain routing graph (graphs.*)
- Provide routing API (pgr_dijkstra, pgr_KSP)
- Snap points to roads
- Update graph when OSM data changes
"""

import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.loguru_config import configure_loguru
from src.db import DatabasePool
from src.graph import GraphBuilder
from src.engine import PgRoutingEngine
from src.api import graph_router
from src.api.routing import router as routing_router


# ==================== Configuration ====================

def load_config() -> dict:
    """Load configuration from environment"""
    return {
        "db": {
            "host": os.getenv("DB_HOST", "postgis"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "database": os.getenv("DB_NAME", "osm"),
            "user": os.getenv("DB_USER", "diplom"),
            "password": os.getenv("DB_PASSWORD", "diplom_pass"),
        }
    }


# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    config = load_config()
    
    logger.info("Initializing router service...")
    
    # 1. Database pool
    app.state.db = DatabasePool(**config["db"])
    await app.state.db.connect()
    
    # 2. GraphBuilder
    logger.info("Creating GraphBuilder...")
    db_cfg = config["db"]
    dsn = (
        f"postgresql://{db_cfg['user']}:{db_cfg['password']}"
        f"@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}"
    )
    app.state.graph_builder = GraphBuilder(
        config_path="configs/router/traffic_config.yaml",
        db_dsn=dsn
    )
    await app.state.graph_builder.initialize()
    logger.info("Checking routing graph...")
    # Graph already exists (built in previous runs), skip rebuild
    
    # 3. PgRouting Engine
    logger.info("Initializing PgRouting engine...")
    app.state.routing_engine = PgRoutingEngine({
        "database": {
            "host": config["db"]["host"],
            "port": config["db"]["port"],
            "name": config["db"]["database"],
            "user": config["db"]["user"],
            "password": config["db"]["password"]
        },
        "connection_pool": {"min_size": 2, "max_size": 10},
        "routing": {"snap_radius_m": 100.0}
    })
    await app.state.routing_engine.initialize()
    
    logger.success("Router service initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down router service...")
    await app.state.routing_engine.close()
    await app.state.db.close()
    logger.info("Router service stopped")


# ==================== FastAPI App ====================

configure_loguru()

app = FastAPI(
    title="Router Service",
    description="Routing graph management and routing API",
    version="1.0.0",
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


# ==================== Health Check ====================

@app.get("/health")
async def health_check():
    """Service health check"""
    try:
        async with app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        return {
            "status": "healthy",
            "service": "router",
            "database": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "router",
            "database": "disconnected",
            "error": str(e)
        }


# ==================== Root ====================

@app.get("/")
async def root():
    """Service info"""
    return {
        "service": "router",
        "version": "1.0.0",
        "description": "Routing graph management and routing API",
        "endpoints": {
            "health": "/health",
            "graph_update": "POST /api/v1/graph/update"
        }
    }


# ==================== API Routes ====================

# Mount graph API
app.include_router(graph_router)

# Mount routing API
app.include_router(routing_router)
