"""
Simulation configuration module.

Defines default parameters for agent simulation.
"""

from dataclasses import dataclass


@dataclass
class SimulationConfig:
    """Configuration for agent simulation."""
    
    # Simulation speed (1.0 = real-time, 100.0 = 100x faster)
    default_sim_speed: float = 30.0
    min_sim_speed: float = 0.25
    max_sim_speed: float = 100.0
    sim_speed_step: float = 1.0
    
    # Rendering FPS (frames per second for UI updates)
    default_fps: int = 30
    min_fps: int = 1
    max_fps: int = 60
    
    # Agent default parameters
    agent_max_speed_kmh: float = 50.0  # km/h (default speed limit)
    agent_length_m: float = 4.5  # meters
    agent_width_m: float = 1.8   # meters
    
    # Agent states
    agent_states = {
        'moving': 'Moving',
        'stopped': 'Stopped',
        'waiting_traffic_light': 'Waiting (Traffic Light)',
        'congestion': 'In Congestion'
    }


# Global config instance
simulation_config = SimulationConfig()
