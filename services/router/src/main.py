"""
Router Service - K-shortest paths with diversity penalties.

Responsibilities:
- Calculate K alternative routes using pgRouting
- Apply diversity penalties (shared edges penalty)
- Turn penalties (two-level: routing + agent physics)
- Priority handling (emergency agents ignore congestion)
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from loguru import logger


from .manager import RouterManager  # noqa: E402
from .models import (  # noqa: E402
    RouteRequest,
    RouteResponse,
    RouteSegment
)


# Global manager
router_manager: RouterManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global router_manager
    
    logger.info("Starting Router Service...")
    
    # Initialize router
    router_manager = RouterManager()
    await router_manager.initialize()
    
    logger.success("Router Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Router Service...")
    await router_manager.shutdown()
    logger.success("Router Service stopped")


app = FastAPI(
    title="Router Service",
    description="K-shortest paths with diversity",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "router"
    }


@app.post("/api/v1/routes", response_model=RouteResponse)
async def calculate_routes(request: RouteRequest):
    """
    Calculate K alternative routes.
    
    Uses pgRouting's Yen algorithm (k-shortest paths).
    Applies diversity penalties to force different paths.
    
    Parameters:
    - start_lat, start_lon: Start point
    - end_lat, end_lon: End point
    - k: Number of routes (default 3)
    - penalty_factor: Shared edges penalty (default 1.5)
    - diversity_threshold: Min diversity (default 0.3)
    - priority: Agent priority (>=20 ignores congestion)
    """
    routes = await router_manager.calculate_routes(
        start_lat=request.start_lat,
        start_lon=request.start_lon,
        end_lat=request.end_lat,
        end_lon=request.end_lon,
        k=request.k,
        penalty_factor=request.penalty_factor,
        diversity_threshold=request.diversity_threshold,
        priority=request.priority,
        agent_type=request.agent_type
    )
    
    return RouteResponse(routes=routes)
