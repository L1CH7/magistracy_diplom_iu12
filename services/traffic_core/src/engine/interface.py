"""Routing Engine Interface - ABC for pluggable routing implementations"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Tuple, Dict
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
    segments: Optional[List[dict]] = None      # Detailed segment info
    
    def __post_init__(self):
        if not self.edge_ids:
            # Allow empty route if same start/end node? For now strict.
            pass 
        if self.total_cost < 0:
            self.total_cost = 0.0
        if self.total_distance_m < 0:
            self.total_distance_m = 0.0
    
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
        pass
    
    @abstractmethod
    async def snap_to_road(
        self,
        lat: float,
        lon: float,
        snap_radius_m: float = 100.0
    ) -> Optional[Tuple[int, float]]:
        pass
    
    @abstractmethod
    async def close(self) -> None:
        pass
