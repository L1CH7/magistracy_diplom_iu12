"""
Config loader for agent physics.

Loads agent configurations from YAML and provides helper functions.
"""

from typing import Dict
from services.common.utils.config_loader import config_loader
from services.common.models.agent import AgentConfig


class AgentConfigManager:
    """
    Manages agent configurations loaded from YAML.
    
    Usage:
        manager = AgentConfigManager()
        config = manager.get_config('car_normal')
        
        # Or with custom params
        config = manager.create_custom(
            base='car_normal',
            max_speed_override_kmh=70
        )
    """
    
    def __init__(self, config_path: str = 'simulation/agent_physics.yaml'):
        """Load agent physics config from YAML."""
        self._config = config_loader.load(config_path)
        self._agent_types = self._config['agent_types']
        self._speed_regions = self._config['speed_penalty_regions']
        self._default_region = self._config['default_region']
        self._physics = self._config['physics']
        
        # Cache loaded configs
        self._cache: Dict[str, AgentConfig] = {}
    
    def get_config(self, agent_type: str = None) -> AgentConfig:
        """
        Get agent config by type name.
        
        Args:
            agent_type: 'car_normal', 'car_hurry', 'emergency', etc.
                       If None, uses default.
        
        Returns:
            AgentConfig instance
        """
        if agent_type is None:
            agent_type = self._config['default_agent']
        
        # Check cache
        if agent_type in self._cache:
            return self._cache[agent_type]
        
        # Load from YAML
        if agent_type not in self._agent_types:
            raise ValueError(
                f"Unknown agent type: {agent_type}. "
                f"Available: {list(self._agent_types.keys())}"
            )
        
        config_dict = self._agent_types[agent_type]
        config = AgentConfig.from_yaml(config_dict)
        
        # Cache it
        self._cache[agent_type] = config
        
        return config
    
    def create_custom(
        self,
        base: str = 'car_normal',
        **overrides
    ) -> AgentConfig:
        """
        Create custom agent config based on preset.
        
        Args:
            base: Base config name
            **overrides: Fields to override
            
        Example:
            config = manager.create_custom(
                base='car_normal',
                priority=10,
                max_speed_override_kmh=70
            )
        """
        base_config = self.get_config(base)
        
        # Create new config with overrides
        config_dict = base_config.__dict__.copy()
        config_dict.update(overrides)
        
        return AgentConfig(**config_dict)
    
    def get_speed_margin(self, region: str = None) -> float:
        """
        Get speed margin for region (non-ticketing limit).
        
        Args:
            region: 'russia', 'turkey', 'belarus', 'europe'
                   If None, uses default.
        
        Returns:
            Margin in km/h (or percent as float)
        """
        if region is None:
            region = self._default_region
        
        if region not in self._speed_regions:
            raise ValueError(
                f"Unknown region: {region}. "
                f"Available: {list(self._speed_regions.keys())}"
            )
        
        region_config = self._speed_regions[region]
        margin_type = region_config['margin_type']
        
        if margin_type == 'absolute':
            return region_config['margin_kmh']
        elif margin_type == 'percent':
            # Return as multiplier (e.g., 10% = 0.10)
            return region_config['margin_percent'] / 100.0
        else:
            raise ValueError(f"Unknown margin_type: {margin_type}")
    
    def calculate_max_allowed_speed(
        self,
        edge_speed_limit_kmh: float,
        region: str = None
    ) -> float:
        """
        Calculate max allowed speed without penalty.
        
        Args:
            edge_speed_limit_kmh: Speed limit from edge data
            region: Region name (or None for default)
        
        Returns:
            Max allowed speed in km/h
        """
        if region is None:
            region = self._default_region
        
        region_config = self._speed_regions[region]
        margin_type = region_config['margin_type']
        
        if margin_type == 'absolute':
            margin = region_config['margin_kmh']
            return edge_speed_limit_kmh + margin
        elif margin_type == 'percent':
            percent = region_config['margin_percent']
            return edge_speed_limit_kmh * (1.0 + percent / 100.0)
        else:
            return edge_speed_limit_kmh
    
    @property
    def physics_config(self) -> dict:
        """Get physics configuration (accel zones, turn thresholds, etc)."""
        return self._physics
    
    @property
    def default_region(self) -> str:
        """Get default speed penalty region."""
        return self._default_region


# Singleton instance
_agent_config_manager = None


def get_agent_config_manager() -> AgentConfigManager:
    """Get singleton agent config manager."""
    global _agent_config_manager
    if _agent_config_manager is None:
        _agent_config_manager = AgentConfigManager()
    return _agent_config_manager
