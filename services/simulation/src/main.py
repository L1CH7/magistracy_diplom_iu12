"""
Simulation Service - FastAPI application.

This service manages agent simulation:
- Holds agent states (AgentBatch)
- Runs simulation tick loop (20 FPS)
- Exposes API for adding/removing/updating agents
- Broadcasts position updates to Coordinator

Key design:
- Stateful service (holds agent states in memory)
- Headless (can run without GUI)
- Optimized for performance (numpy vectorization)
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger

from .manager import SimulationManager
from .models import (
    AddAgentRequest,
    AddAgentResponse,
    UpdateRouteRequest,
    SimulationStatusResponse
)


# Global simulation manager
sim_manager: SimulationManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global sim_manager
    
    logger.info("Starting Simulation Service...")
    
    # Initialize simulation manager
    sim_manager = SimulationManager()
    await sim_manager.initialize()
    
    logger.success("Simulation Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Simulation Service...")
    await sim_manager.shutdown()
    logger.success("Simulation Service stopped")


# Create FastAPI app
app = FastAPI(
    title="Simulation Service",
    description="Agent simulation engine for multi-agent navigation system",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "simulation",
        "running": sim_manager.is_running if sim_manager else False,
        "agents": sim_manager.get_agent_count() if sim_manager else 0
    }


@app.post("/simulation/start")
async def start_simulation():
    """Start simulation loop."""
    if sim_manager.is_running:
        raise HTTPException(400, "Simulation already running")
    
    await sim_manager.start()
    
    logger.info("Simulation started")
    return {"status": "started"}


@app.post("/simulation/stop")
async def stop_simulation():
    """Stop simulation loop."""
    if not sim_manager.is_running:
        raise HTTPException(400, "Simulation not running")
    
    await sim_manager.stop()
    
    logger.info("Simulation stopped")
    return {"status": "stopped"}


@app.get("/simulation/status")
async def get_status() -> SimulationStatusResponse:
    """Get simulation status."""
    return sim_manager.get_status()


@app.post("/simulation/agents", response_model=AddAgentResponse)
async def add_agent(request: AddAgentRequest) -> AddAgentResponse:
    """
    Add new agent to simulation.
    
    Args:
        request: Agent configuration and route
        
    Returns:
        Agent ID and initial position
    """
    try:
        agent_id = await sim_manager.add_agent(
            route_edge_ids=request.route_edge_ids,
            start_lat=request.start_lat,
            start_lon=request.start_lon,
            agent_type=request.agent_type,
            config_overrides=request.config_overrides
        )
        
        # Get initial position
        position = sim_manager.get_agent_position(agent_id)
        
        logger.info(f"Added agent {agent_id}")
        
        return AddAgentResponse(
            agent_id=agent_id,
            position=position
        )
        
    except Exception as e:
        logger.error(f"Failed to add agent: {e}")
        raise HTTPException(500, f"Failed to add agent: {str(e)}")


@app.delete("/simulation/agents/{agent_id}")
async def remove_agent(agent_id: str):
    """Remove agent from simulation."""
    try:
        await sim_manager.remove_agent(agent_id)
        logger.info(f"Removed agent {agent_id}")
        return {"status": "removed"}
    except KeyError:
        raise HTTPException(404, f"Agent {agent_id} not found")
    except Exception as e:
        logger.error(f"Failed to remove agent: {e}")
        raise HTTPException(500, str(e))


@app.put("/simulation/agents/{agent_id}/route")
async def update_route(agent_id: str, request: UpdateRouteRequest):
    """
    Update agent's route (if can switch at current position).
    
    Args:
        agent_id: Agent ID
        request: New route
        
    Returns:
        Success status and new route index (if switched)
    """
    try:
        success, new_index = await sim_manager.update_route(
            agent_id,
            request.route_edge_ids
        )
        
        if success:
            logger.info(
                f"Agent {agent_id} switched to new route at index {new_index}"
            )
            return {
                "status": "switched",
                "new_route_index": new_index
            }
        else:
            logger.warning(f"Agent {agent_id} cannot switch route")
            return {
                "status": "cannot_switch",
                "reason": "No overlap with current position"
            }
            
    except KeyError:
        raise HTTPException(404, f"Agent {agent_id} not found")
    except Exception as e:
        logger.error(f"Failed to update route: {e}")
        raise HTTPException(500, str(e))


@app.get("/simulation/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get agent state."""
    try:
        state = sim_manager.get_agent_state(agent_id)
        return state
    except KeyError:
        raise HTTPException(404, f"Agent {agent_id} not found")


@app.get("/simulation/agents")
async def list_agents():
    """List all agents."""
    agents = sim_manager.list_agents()
    return {"agents": agents, "count": len(agents)}


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc)
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info"
    )
