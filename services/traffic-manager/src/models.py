"""
Traffic Manager data models.
"""

from typing import List, Dict
from pydantic import BaseModel, Field


class EdgeCongestionRequest(BaseModel):
    """Request for edge congestion levels."""
    
    edge_ids: List[int] = Field(
        ...,
        description="List of edge IDs to check"
    )


class EdgeCongestionResponse(BaseModel):
    """Response with edge congestion levels."""
    
    congestion: Dict[int, float] = Field(
        ...,
        description="Map: edge_id -> congestion_level (0.0 to 2.0+)"
    )


class CongestionStatsResponse(BaseModel):
    """Global congestion statistics."""
    
    total_edges: int = Field(..., description="Total edges in graph")
    
    congested_edges: int = Field(
        ...,
        description="Edges with congestion > threshold (0.8)"
    )
    
    avg_congestion: float = Field(
        ...,
        ge=0.0,
        description="Average congestion level"
    )
    
    max_congestion: float = Field(
        ...,
        ge=0.0,
        description="Maximum congestion level"
    )
