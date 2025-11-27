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
from src.api import graph_router


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
    app.state.graph_builder = GraphBuilder(
        db_pool=app.state.db.pool,
        config={}
    )
    logger.info("Checking routing graph...")
    await app.state.graph_builder.ensure_graph_exists()
    
    logger.success("Router service initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down router service...")
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

# TODO: Add routing API endpoints
# - POST /api/v1/route/find
# - POST /api/v1/route/snap
