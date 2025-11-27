"""
Router Service data models (API layer).
"""

from typing import List
from pydantic import BaseModel, Field

from .engine import Route as EngineRoute


class RouteRequest(BaseModel):
    """Route calculation request."""
    
    start_lat: float = Field(..., description="Start latitude")
    start_lon: float = Field(..., description="Start longitude")
    end_lat: float = Field(..., description="End latitude")
    end_lon: float = Field(..., description="End longitude")
    k: int = Field(default=3, ge=1, le=10, description="Number of routes")
    
    priority: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Agent priority (>=20 emergency, ignores congestion)"
    )
    
    agent_type: str = Field(
        default="normal",
        description="Agent mode (normal, hurry, cautious, emergency)"
    )


class RouteResponse(BaseModel):
    """Response with K routes."""
    
    routes: List[EngineRoute] = Field(
        ...,
        description="Alternative routes"
    )
    
    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True
