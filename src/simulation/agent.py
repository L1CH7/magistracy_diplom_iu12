from dataclasses import dataclass
from typing import List


@dataclass
class AgentParams:
    max_speed: float  # m/s
    power: float      # abstract acceleration capability
    length: float     # meters
    width: float      # meters


@dataclass
class AgentState:
    route_nodes: List[int]
    index: int = 0
    position_lat: float = 0.0
    position_lon: float = 0.0
    speed: float = 0.0
