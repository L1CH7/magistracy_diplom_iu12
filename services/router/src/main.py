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

from services.common.utils.loguru_config import configure_loguru
from src.db import DatabasePool
from src.graph_builder import GraphBuilder
from src.db_manager import PostGISManager
from src.engine import PgRoutingEngine
from src.api import graph_router
from src.api import  routing_router
from prometheus_client import make_asgi_app


# ==================== Configuration ====================

from services.common.config import load_settings, Settings
from services.common.config.settings import ServiceConfig

def get_settings() -> Settings:
    return load_settings()


# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    settings = get_settings()
    
    logger.info("Initializing router service...")
    
    # 1. Database pool
    db_config = {
        "host": settings.db.host,
        "port": settings.db.port,
        "database": settings.db.name,
        "user": settings.db.user,
        "password": settings.db.password,
    }
    app.state.db = DatabasePool(**db_config)
    await app.state.db.connect()
    
    # 2. GraphBuilder (Restored & Fixed)
    logger.info("Initializing GraphBuilder...")
    app.state.db_manager = PostGISManager() # Sync connection for build
    app.state.graph_builder = GraphBuilder(app.state.db_manager)
    
    # 3. PgRouting Engine
    logger.info("Initializing PgRouting engine...")
    app.state.routing_engine = PgRoutingEngine({
        "database": db_config,
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

configure_loguru(service_name="router")

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
            "graph_build": "POST /api/v1/graph/build",
            "graph_status": "GET /api/v1/graph/status/{task_id}",
        }
    }


# ==================== API Routes ====================

# Mount graph API
app.include_router(graph_router)

# Mount routing API
app.include_router(routing_router)

# Expose Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Suppress /metrics access logs
import logging
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/metrics" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())
