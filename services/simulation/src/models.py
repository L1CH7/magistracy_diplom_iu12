"""
Pydantic models for Simulation Service API.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class AddAgentRequest(BaseModel):
    """Request to add new agent."""
    route_edge_ids: List[int] = Field(..., description="Route as edge IDs")
    start_lat: float = Field(..., description="Starting latitude")
    start_lon: float = Field(..., description="Starting longitude")
    agent_type: str = Field(
        default="car_normal",
        description="Agent type (car_normal, car_hurry, emergency, truck)"
    )
    config_overrides: Optional[Dict] = Field(
        default=None,
        description="Override agent config params"
    )


class AgentPosition(BaseModel):
    """Agent position data."""
    lat: float
    lon: float
    speed_mps: float
    bearing_degrees: float
    edge_id: int
    edge_progress: float


class AddAgentResponse(BaseModel):
    """Response from adding agent."""
    agent_id: str
    position: AgentPosition


class UpdateRouteRequest(BaseModel):
    """Request to update agent route."""
    route_edge_ids: List[int] = Field(..., description="New route edge IDs")


class SimulationStatusResponse(BaseModel):
    """Simulation status."""
    is_running: bool
    fps: float
    agent_count: int
    running_agents: int
    completed_agents: int
    elapsed_time: float
    total_distance_m: float


class AgentStateResponse(BaseModel):
    """Agent state for API."""
    agent_id: str
    position: AgentPosition
    is_running: bool
    reached_destination: bool
    total_distance_m: float
    elapsed_time: float
