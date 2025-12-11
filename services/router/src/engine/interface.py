"""Routing Engine Interface - ABC for pluggable routing implementations"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Tuple
from dataclasses import dataclass


class RoutingAlgorithm(Enum):
    """Supported routing algorithms"""
    PGROUTING = "pgrouting"
    ASTAR = "astar"


class RouteNotFoundError(Exception):
    """Raised when no route can be found between start and end"""
    pass


@dataclass
class Route:
    """Represents a calculated route"""
    edge_ids: List[int]
    total_cost: float  # in seconds
    total_distance_m: float
    algorithm: str
    node_sequence: Optional[List[int]] = None  # Node IDs in traversal order
    
    def __post_init__(self):
        if not self.edge_ids:
            raise ValueError("Route must have at least one edge")
        if self.total_cost < 0:
            raise ValueError("Total cost cannot be negative")
        if self.total_distance_m < 0:
            raise ValueError("Total distance cannot be negative")
    
    def to_dict(self):
        return {
            'edge_ids': self.edge_ids,
            'total_cost': round(self.total_cost, 2),
            'total_distance_m': round(self.total_distance_m, 2),
            'algorithm': self.algorithm,
            'node_sequence': self.node_sequence
        }


class RoutingEngine(ABC):
    """
    Abstract routing engine interface.
    
    Implementations:
    - PgRoutingEngine: Uses pgRouting (pgr_dijkstra, pgr_KSP)
    - AStarEngine: Custom A* + Yen's implementation (future)
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize routing engine (connect to DB, load config, etc.)"""
        pass
    
    @abstractmethod
    async def find_route(
        self,
        start_node: int,
        end_node: int,
        priority: int = 0
    ) -> Route:
        """
        Find shortest route from start to end.
        
        Args:
            start_node: Starting node ID
            end_node: Ending node ID
            priority: Agent priority (0-100, higher = ignore congestion)
        
        Returns:
            Route object with edge_ids and costs
        
        Raises:
            RouteNotFoundError: If no route exists
        """
        pass
    
    @abstractmethod
    async def find_k_routes(
        self,
        start_node: int,
        end_node: int,
        k: int = 3,
        priority: int = 0,
        use_diversity: bool = False
    ) -> List[Route]:
        """
        Find K alternative routes.
        
        Args:
            start_node: Starting node ID
            end_node: Ending node ID
            k: Number of routes to find
            priority: Agent priority (higher = faster routes)
            use_diversity: Apply diversity filtering (optional, slower)
        
        Returns:
            List of Route objects (sorted by cost)
        
        Raises:
            RouteNotFoundError: If no routes exist
        """
        pass
    
    @abstractmethod
    async def snap_to_road(
        self,
        lat: float,
        lon: float,
        snap_radius_m: float = 100.0
    ) -> Optional[Tuple[int, float]]:
        """
        Snap GPS coordinates to nearest road edge.
        
        Args:
            lat: Latitude
            lon: Longitude
            snap_radius_m: Maximum search radius in meters
        
        Returns:
            (edge_id, position_meters) or None if no edge found
        """
        pass
    
    @abstractmethod
    async def update_edge_load(
        self,
        edge_id: int,
        new_load: int
    ) -> None:
        """
        Update traffic load on edge (for congestion model).
        
        Args:
            edge_id: Edge ID
            new_load: New current_load value
        """
        pass
    
    @abstractmethod
    async def get_graph_stats(self) -> dict:
        """
        Get graph statistics.
        
        Returns:
            Dict with keys: nodes, edges, total_distance_m, algorithm
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close connections and cleanup"""
        pass
