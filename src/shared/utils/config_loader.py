"""
Simplified config loader for standalone services.

Loads YAML configs without external dependencies.
"""

import yaml
from pathlib import Path
from typing import Dict, Any


class SimpleConfigLoader:
    """Load YAML configs from configs/ directory."""
    
    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)
        self._cache: Dict[str, Any] = {}
    
    def load(self, config_name: str) -> Dict[str, Any]:
        """Load config by name."""
        if config_name in self._cache:
            return self._cache[config_name]
        
        config_path = self.config_dir / config_name
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self._cache[config_name] = config
        return config
    
    def get_agent_config(self, agent_type: str = "car_normal") -> Dict:
        """Get agent physics config."""
        physics = self.load("simulation/agent_physics.yaml")
        return physics.get("agent_types", {}).get(agent_type, {})


# Global instance
config_loader = SimpleConfigLoader()
