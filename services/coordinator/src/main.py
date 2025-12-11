"""
Coordinator Service - orchestrates multi-agent navigation.

Responsibilities:
- Calculate K alternative routes
- Assign routes to agents (with priority handling)
- Monitor congestion and trigger rerouting
- WebSocket hub for GUI clients
"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from loguru import logger


from .manager import CoordinatorManager  # noqa: E402
from .models import (  # noqa: E402
    CalculateRoutesRequest,
    CalculateRoutesResponse,
    AssignRouteRequest,
    AssignRouteResponse,
    ReroutingStatusResponse
)

# Global manager
coordinator_manager: CoordinatorManager = None

# WebSocket connections (GUI clients)
websocket_connections: Set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global coordinator_manager
    
    logger.info("Starting Coordinator Service...")
    
    # Initialize coordinator
    coordinator_manager = CoordinatorManager()
    await coordinator_manager.initialize()
    
    logger.success("Coordinator Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Coordinator Service...")
    await coordinator_manager.shutdown()
    logger.success("Coordinator Service stopped")


app = FastAPI(
    title="Coordinator Service",
    description="Multi-agent navigation coordination",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "coordinator",
        "websocket_clients": len(websocket_connections),
        "agents_managed": coordinator_manager.get_agent_count()
    }


@app.post("/api/v1/routes/calculate", response_model=CalculateRoutesResponse)
async def calculate_routes(request: CalculateRoutesRequest):
    """
    Calculate K alternative routes with diversity penalties.
    
    Uses pgRouting for graph search.
    Applies diversity_threshold to find different paths.
    """
    waypoints = request.get_waypoints()
    
    routes = await coordinator_manager.calculate_routes(
        start_lat=waypoints[0][0],
        start_lon=waypoints[0][1],
        end_lat=waypoints[-1][0],
        end_lon=waypoints[-1][1],
        k=request.k,
        priority=request.priority,
        agent_type=request.agent_type
    )
    
    return CalculateRoutesResponse(routes=routes)


@app.post("/api/v1/agents", response_model=AssignRouteResponse)
async def create_agent(request: AssignRouteRequest):
    """
    Create agent and assign route.
    
    Flow:
    1. Validate route (optional)
    2. Call Simulation Service to create agent
    3. Register in coordinator
    4. Return agent_id
    """
    agent_id = await coordinator_manager.create_agent(
        start_lat=request.start_lat,
        start_lon=request.start_lon,
        end_lat=request.end_lat,
        end_lon=request.end_lon,
        route_edge_ids=request.route_edge_ids,
        priority=request.priority,
        agent_type=request.agent_type
    )
    
    return AssignRouteResponse(
        agent_id=agent_id,
        status="created"
    )


@app.delete("/api/v1/agents/{agent_id}")
async def remove_agent(agent_id: str):
    """Remove agent from system."""
    try:
        await coordinator_manager.remove_agent(agent_id)
        return {"status": "removed"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")


@app.get("/api/v1/rerouting/status", response_model=ReroutingStatusResponse)
async def get_rerouting_status():
    """Get rerouting service status and statistics."""
    status = await coordinator_manager.get_rerouting_status()
    
    return ReroutingStatusResponse(
        enabled=status["enabled"],
        strategy=status["strategy"],
        check_interval_sec=status["check_interval_sec"],
        last_rerouting_time=status["last_rerouting_time"],
        agents_rerouted=status["agents_rerouted"],
        congestion_threshold=status["congestion_threshold"]
    )


@app.websocket("/ws/positions")
async def websocket_positions(websocket: WebSocket):
    """
    WebSocket endpoint for real-time agent positions.
    
    Flow:
    1. GUI client connects
    2. Coordinator broadcasts positions from Simulation Service
    3. Client receives updates @ 20 FPS
    """
    await websocket.accept()
    websocket_connections.add(websocket)
    
    logger.info(
        f"WebSocket client connected "
        f"(total: {len(websocket_connections)})"
    )
    
    try:
        # Keep connection alive
        while True:
            # Wait for messages from client (heartbeat)
            try:
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await websocket.send_json({"type": "ping"})
                
    except WebSocketDisconnect:
        websocket_connections.remove(websocket)
        logger.info(
            f"WebSocket client disconnected "
            f"(remaining: {len(websocket_connections)})"
        )
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=e)
        websocket_connections.discard(websocket)


async def broadcast_positions(positions: List[Dict]):
    """
    Broadcast agent positions to all connected GUI clients.
    
    Called by CoordinatorManager when receiving updates
    from Simulation Service.
    """
    if not websocket_connections:
        return
    
    message = {
        "type": "positions",
        "data": positions
    }
    
    # Send to all clients (parallel)
    await asyncio.gather(
        *[ws.send_json(message) for ws in websocket_connections],
        return_exceptions=True
    )


# Global reference for CoordinatorManager
def set_broadcast_callback(manager):
    """Set broadcast callback for manager."""
    manager.broadcast_callback = broadcast_positions


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
