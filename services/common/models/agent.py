"""
Agent models - lightweight dataclasses for agent state.

These are PURE DATA structures - no methods, no logic.
All logic is in separate pure functions (see agent/movement.py).
"""

from dataclasses import dataclass, field
from typing import Tuple, List


@dataclass
class AgentConfig:
    """
    Agent configuration - type-specific parameters.
    
    Loaded from configs/simulation/agent_physics.yaml.
    This defines HOW the agent moves (physics), not WHERE.
    """
    agent_type: str  # 'car', 'truck', 'bus', 'emergency'
    priority: int  # 0=normal, 10=special, 20=emergency
    acceleration_mps2: float  # m/s² - how fast it accelerates
    deceleration_mps2: float  # m/s² - how fast it brakes
    turn_speed_factor: float  # 0.4-1.0 - speed reduction on turns
    driver_mode: str  # 'patient', 'normal', 'hurry'
    driver_speed_factor: float  # 0.85-1.0 - how close to limit
    max_speed_override_kmh: float | None  # Override max speed (or None)
    ignore_capacity: bool = False  # Emergency vehicles ignore traffic
    
    @staticmethod
    def from_yaml(config_dict: dict) -> 'AgentConfig':
        """Create AgentConfig from YAML dict."""
        return AgentConfig(
            agent_type=config_dict['type'],
            priority=config_dict['priority'],
            acceleration_mps2=config_dict['acceleration_mps2'],
            deceleration_mps2=config_dict['deceleration_mps2'],
            turn_speed_factor=config_dict['turn_speed_factor'],
            driver_mode=config_dict['driver_mode'],
            driver_speed_factor=config_dict['driver_speed_factor'],
            max_speed_override_kmh=config_dict.get(
                'max_speed_override_kmh'
            ),
            ignore_capacity=config_dict.get('ignore_capacity', False)
        )


@dataclass
class AgentState:
    """
    Lightweight agent state - minimal data for simulation.
    
    IMPORTANT: This is PURE DATA, no methods!
    All operations on state are pure functions in movement.py.
    
    Design for 1000 agents:
    - Small memory footprint (~200 bytes per agent)
    - No nested objects (flat structure)
    - Can be vectorized with numpy
    """
    agent_id: str
    
    # Current position
    lat: float
    lon: float
    
    # Current edge and progress
    edge_id: int  # Current edge in graph
    edge_progress: float  # 0.0-1.0 progress along edge
    
    # Route
    route_edge_ids: List[int]  # List of edge IDs to follow
    route_index: int  # Current position in route
    
    # Movement
    current_speed_mps: float  # Current speed in m/s
    bearing_degrees: float  # Direction of movement (0-360)
    
    # Simulation time
    start_time: float  # Unix timestamp when agent started
    elapsed_time: float  # Seconds elapsed in simulation
    
    # Status
    is_running: bool  # Is agent moving?
    reached_destination: bool  # Has agent finished?
    
    # Config reference (not copied - lightweight)
    config: AgentConfig = field(default=None)
    
    # Stats
    total_distance_m: float = 0.0  # Total distance traveled
    
    def __repr__(self) -> str:
        """Compact repr for logging."""
        return (
            f"Agent({self.agent_id}, "
            f"pos=({self.lat:.6f},{self.lon:.6f}), "
            f"edge={self.edge_id}, "
            f"speed={self.current_speed_mps:.1f}m/s, "
            f"running={self.is_running})"
        )


@dataclass
class Route:
    """
    Route data structure.
    
    This is returned by Router Service and stored in Coordinator.
    """
    route_id: int
    edge_ids: List[int]  # Sequence of edges to follow
    geometry: List[Tuple[float, float]]  # (lon, lat) coordinates
    total_distance_m: float
    estimated_time_sec: float
    
    # Optional metadata
    name: str = ""
    description: str = ""


@dataclass
class TeleportAlert:
    """Alert for teleportation detection."""
    agent_id: str
    timestamp: float
    expected_distance_m: float
    actual_distance_m: float
    lat: float
    lon: float
