from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Route:
    nodes: List[int]
    total_distance: float
    estimated_time: float


class RouteEngine(ABC):
    @abstractmethod
    def get_k_routes(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        k: int = 1,
    ) -> List[Route]:
        raise NotImplementedError
