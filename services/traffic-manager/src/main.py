"""
Traffic Manager Service - real-time traffic state management.

Responsibilities:
- Track edge loads (current_load from Simulation Service)
- Calculate congestion levels (load / capacity)
- Detect congested edges (> threshold)
- Provide congestion data for routing and rerouting
- Cache in Redis for fast access
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

sys.path.append(str(Path(__file__).parents[3]))

from .manager import TrafficManager  # noqa: E402
from .models import (  # noqa: E402
    CongestionStatsResponse,
    EdgeCongestionRequest,
    EdgeCongestionResponse
)


# Global manager
traffic_manager: TrafficManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global traffic_manager
    
    logger.info("Starting Traffic Manager Service...")
    
    # Initialize manager
    traffic_manager = TrafficManager()
    await traffic_manager.initialize()
    
    logger.success("Traffic Manager Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Traffic Manager Service...")
    await traffic_manager.shutdown()
    logger.success("Traffic Manager Service stopped")


app = FastAPI(
    title="Traffic Manager Service",
    description="Real-time traffic state management",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "traffic-manager"
    }


@app.get("/api/v1/congestion/stats", response_model=CongestionStatsResponse)
async def get_congestion_stats():
    """
    Get global congestion statistics.
    
    Returns:
    - total_edges: Total edges in graph
    - congested_edges: Edges with congestion > threshold
    - avg_congestion: Average congestion level
    - max_congestion: Maximum congestion level
    """
    stats = await traffic_manager.get_congestion_stats()
    
    return CongestionStatsResponse(**stats)


@app.post("/api/v1/congestion/edges", response_model=EdgeCongestionResponse)
async def get_edge_congestion(request: EdgeCongestionRequest):
    """
    Get congestion levels for specific edges.
    
    Input: list of edge_ids
    Output: dict {edge_id: congestion_level}
    """
    congestion = await traffic_manager.get_edge_congestion(
        request.edge_ids
    )
    
    return EdgeCongestionResponse(congestion=congestion)


@app.get("/api/v1/congestion/hotspots")
async def get_hotspots(limit: int = 10):
    """
    Get top N most congested edges.
    
    Returns: list of (edge_id, congestion_level)
    """
    hotspots = await traffic_manager.get_hotspots(limit)
    
    return {"hotspots": hotspots}
