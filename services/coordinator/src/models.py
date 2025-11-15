"""Pydantic models for Coordinator API."""

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class Point(BaseModel):
    """Geographic point."""
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class RouteSegment(BaseModel):
    """Single segment of route."""
    edge_id: int
    length_m: float
    speed_limit_kmh: int
    estimated_time_sec: float


class Route(BaseModel):
    """Complete route with segments."""
    route_id: int
    segments: List[RouteSegment]
    total_distance_m: float
    estimated_time_sec: float
    diversity_score: float = Field(
        ...,
        description="Uniqueness compared to other routes (0-1)"
    )


class CalculateRoutesRequest(BaseModel):
    """Request to calculate K alternative routes."""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    k: int = Field(3, description="Number of alternative routes")
    priority: int = Field(
        0, description="Agent priority (0=normal, 20=emergency)"
    )
    agent_type: str = Field("car_normal", description="Agent type")


class CalculateRoutesResponse(BaseModel):
    """Response with K alternative routes."""
    routes: List[Route]


class AssignRouteRequest(BaseModel):
    """Request to create agent with route."""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    route_edge_ids: Optional[List[int]] = Field(
        None,
        description="Explicit route (if None, Coordinator calculates)"
    )
    priority: int = Field(0, description="Agent priority")
    agent_type: str = Field("car_normal", description="Agent type")
    config_overrides: Optional[Dict] = None


class AssignRouteResponse(BaseModel):
    """Response after creating agent."""
    agent_id: str
    route_edge_ids: List[int]
    estimated_time_sec: float


class ReroutingStatusResponse(BaseModel):
    """Rerouting service status."""
    enabled: bool
    strategy: str  # "fixed" | "event_driven" | "hybrid"
    check_interval_sec: int
    last_rerouting_time: Optional[float] = None
    agents_rerouted: int
    congestion_threshold: float


class AgentPositionUpdate(BaseModel):
    """Agent position update (from Simulation Service)."""
    agent_id: str
    lat: float
    lon: float
    speed_mps: float
    bearing_degrees: float
    edge_id: int
    edge_progress: float
