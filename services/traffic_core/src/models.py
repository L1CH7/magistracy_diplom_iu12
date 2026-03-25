"""
Router Service data models.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    """Route calculation request."""
    
    start_lat: float = Field(..., description="Start latitude")
    start_lon: float = Field(..., description="Start longitude")
    end_lat: float = Field(..., description="End latitude")
    end_lon: float = Field(..., description="End longitude")
    k: int = Field(default=3, ge=1, le=10, description="Number of routes")
    
    penalty_factor: float = Field(
        default=1.5,
        ge=1.0,
        le=5.0,
        description="Shared edges penalty multiplier"
    )
    
    diversity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Min diversity (0 = identical OK, 1 = fully different)"
    )
    
    priority: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Agent priority (>=20 emergency, ignores congestion)"
    )
    
    agent_type: str = Field(
        default="car_normal",
        description="Agent type (car_normal, car_fast, etc)"
    )


class RouteSegment(BaseModel):
    """Route segment (edge)."""
    
    edge_id: int = Field(..., description="Edge ID")
    from_node: int = Field(..., description="From node ID")
    to_node: int = Field(..., description="To node ID")
    distance_m: float = Field(..., description="Segment length (meters)")
    speed_limit: float = Field(..., description="Speed limit (m/s)")
    
    effective_speed: Optional[float] = Field(
        None,
        description="Current speed with congestion (m/s)"
    )
    
    bearing: Optional[float] = Field(
        None,
        description="Bearing (degrees, 0-360)"
    )
    
    geometry: Optional[dict] = Field(
        None,
        description="GeoJSON geometry (LineString)"
    )


class Route(BaseModel):
    """Single route."""
    
    route_id: int = Field(..., description="Route index (0, 1, 2...)")
    
    segments: List[RouteSegment] = Field(
        ...,
        description="List of edges"
    )
    
    total_distance_m: float = Field(..., description="Total distance (meters)")
    
    estimated_time_sec: float = Field(
        ...,
        description="Estimated time (seconds)"
    )
    
    diversity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Diversity vs route 0 (0=identical, 1=fully different)"
    )
    
    edge_ids: List[int] = Field(
        ...,
        description="Edge IDs (for convenience)"
    )


class RouteResponse(BaseModel):
    """Response with K routes."""
    
    routes: List[Route] = Field(..., description="Alternative routes")
