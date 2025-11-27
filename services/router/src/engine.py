"""
Router Engine interface - ABC for pluggable routing algorithms.

Allows easy switching between pgRouting and A* implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class RouteSegment:
    """Single edge in a route."""
    edge_id: int
    from_node: int
    to_node: int
    distance_m: float
    time_sec: float
    speed_limit_kmh: float
    effective_speed_kmh: float
    bearing: float | None = None


@dataclass
class Route:
    """Complete route from start to end."""
    route_id: int
    segments: List[RouteSegment]
    total_distance_m: float
    estimated_time_sec: float
    diversity_score: float  # 0.0 = identical to route 0, 1.0 = fully different
    edge_ids: List[int]  # Convenience list


class RouteEngine(ABC):
    """
    Abstract base class for routing engines.
    
    Implementations:
    - PgRoutingEngine: Uses pgRouting SQL functions (Dijkstra/Yen)
    - AStarEngine: Uses custom A* + Yen implementation (src/routing/)
    """
    
    @abstractmethod
    async def initialize(self):
        """Initialize engine (load graph, setup DB pool, etc)."""
        pass
    
    @abstractmethod
    async def shutdown(self):
        """Cleanup resources."""
        pass
    
    @abstractmethod
    async def calculate_routes(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        k: int = 3,
        agent_mode: str = "normal",
        priority: int = 0
    ) -> List[Route]:
        """
        Calculate K alternative routes.
        
        Args:
            start_lat, start_lon: Start coordinates
            end_lat, end_lon: End coordinates
            k: Number of routes to return
            agent_mode: Agent behavior mode (normal, hurry, cautious, emergency)
            priority: Agent priority (0-100, >=20 emergency)
        
        Returns:
            List of Route objects, sorted by estimated_time_sec
        """
        pass
    
    @abstractmethod
    async def snap_to_road(
        self,
        lat: float,
        lon: float,
        k: int = 5,
        max_distance_m: float = 100.0
    ) -> List[Tuple[int, float]]:
        """
        Snap point to nearest road edges.
        
        Args:
            lat, lon: Point coordinates
            k: Number of nearest edges to return
            max_distance_m: Maximum snap distance
        
        Returns:
            List of (edge_id, distance_m) tuples
        """
        pass
