"""Route model."""
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class Route:
    """Calculated route.
    
    Attributes:
        nodes: List of node IDs in the route
        edges: List of edge dicts (from graph)
        distance_m: Total distance in meters
        duration_s: Total duration in seconds
        coordinates: List of (lon, lat) tuples for rendering
    """
    nodes: List[int]
    edges: List[Dict[str, Any]]
    distance_m: float
    duration_s: float
    coordinates: List[tuple] = None
    
    def __post_init__(self):
        """Initialize coordinates if not provided."""
        if self.coordinates is None:
            self.coordinates = []
    
    def get_distance_km(self) -> float:
        """Get distance in kilometers."""
        return self.distance_m / 1000.0
    
    def get_duration_minutes(self) -> float:
        """Get duration in minutes."""
        return self.duration_s / 60.0
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            'nodes': self.nodes,
            'edges': self.edges,
            'distance_m': self.distance_m,
            'duration_s': self.duration_s,
            'coordinates': self.coordinates,
        }
