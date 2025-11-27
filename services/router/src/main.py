"""
Router Service - K-shortest paths with pluggable algorithms.

Responsibilities:
- Calculate K alternative routes (A* or pgRouting)
- Apply diversity penalties (shared edges penalty)
- Turn penalties (two-level: routing + agent physics)
- Priority handling (emergency agents ignore congestion)
- Agent modes (normal, hurry, cautious, emergency)
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from loguru import logger


# Configure logging to file
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)
logger.add(
    "logs/router.log",
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}"
)


from .manager import RouterManager  # noqa: E402
from .models import (  # noqa: E402
    RouteRequest,
    RouteResponse
)


# Global manager
router_manager: RouterManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global router_manager
    
    logger.info("Starting Router Service...")
    
    # Initialize router with config
    router_manager = RouterManager(config_path="configs/router.yaml")
    await router_manager.initialize()
    
    logger.success("Router Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Router Service...")
    await router_manager.shutdown()
    logger.success("Router Service stopped")


app = FastAPI(
    title="Router Service",
    description="K-shortest paths routing (A* or pgRouting)",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "router",
        "algorithm": router_manager.config.get("algorithm", "unknown")
    }


@app.post("/api/v1/routes", response_model=RouteResponse)
async def calculate_routes(request: RouteRequest):
    """
    Calculate K alternative routes.
    
    Supports pluggable algorithms (A*, pgRouting).
    Applies diversity penalties and turn penalties.
    
    Parameters:
    - start_lat, start_lon: Start point
    - end_lat, end_lon: End point
    - k: Number of routes (default 3)
    - agent_type: Agent mode (normal, hurry, cautious, emergency)
    - priority: Agent priority (>=20 ignores congestion)
    """
    routes = await router_manager.calculate_routes(
        start_lat=request.start_lat,
        start_lon=request.start_lon,
        end_lat=request.end_lat,
        end_lon=request.end_lon,
        k=request.k,
        agent_mode=request.agent_type,
        priority=request.priority
    )
    
    return RouteResponse(routes=routes)
