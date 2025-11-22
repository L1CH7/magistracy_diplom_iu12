"""
Configuration loader with hot reload support for YAML configs.

Features:
- YAML loading with !include directive support
- Caching for performance
- Environment variable expansion: ${VAR:default}
- Hot reload via reload() method
- Auto-detects /app/configs (container) or project configs/ (dev)

Usage:
    from src.utils.config_loader import config_loader
    
    # Load config
    config = config_loader.load('client/data.yaml')
    
    # Access values
    timeout = config['api']['timeout_default']
    
    # Reload after changes
    config_loader.reload('client/data.yaml')
    
    # Use includes in YAML:
    # map.yaml:
    #   lod: !include map.lod.yaml
    #   rendering: !include map.rendering.yaml
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict
from loguru import logger


class IncludeLoader(yaml.SafeLoader):
    """Custom YAML loader that supports !include directive."""
    
    def __init__(self, stream):
        self._root = Path(stream.name).parent if hasattr(stream, 'name') else Path.cwd()
        super().__init__(stream)


def include_constructor(loader: IncludeLoader, node: yaml.Node) -> Any:
    """Construct included YAML file."""
    # Get the path from the node
    include_path = loader.construct_scalar(node)
    
    # Resolve relative to current file
    full_path = loader._root / include_path
    
    # Load the included file
    with open(full_path, 'r', encoding='utf-8') as f:
        return yaml.load(f, IncludeLoader)


# Register the include constructor
yaml.add_constructor('!include', include_constructor, IncludeLoader)


class ConfigLoader:
    """Manages YAML configuration loading with caching and hot reload."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._config_root = self._detect_config_root()
        logger.info(f"ConfigLoader initialized with root: {self._config_root}")
    
    def _detect_config_root(self) -> Path:
        """Detect config root directory (container or dev environment)."""
        # Try container path first
        container_path = Path('/app/configs')
        if container_path.exists():
            return container_path
        
        # Fall back to project root
        from src.utils.project_root import PROJECT_ROOT
        config_path = PROJECT_ROOT / 'configs'
        
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config directory not found. Tried:\n"
                f"  - {container_path}\n"
                f"  - {config_path}"
            )
        
        return config_path
    
    def load(self, config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file with !include support.
        
        Args:
            config_path: Relative path from config root (e.g., 'client/data.yaml')
        
        Returns:
            Parsed configuration dictionary
        """
        # Check cache first
        if config_path in self._cache:
            logger.debug(f"Config loaded from cache: {config_path}")
            return self._cache[config_path]
        
        # Load from file
        full_path = self._config_root / config_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_path}")
        
        logger.info(f"Loading config: {config_path}")
        
        with open(full_path, 'r', encoding='utf-8') as f:
            config = yaml.load(f, IncludeLoader)
        
        # Expand environment variables
        config = self._expand_env_vars(config)
        
        # Cache and return
        self._cache[config_path] = config
        return config
    
    def reload(self, config_path: str) -> Dict[str, Any]:
        """
        Force reload configuration from disk (clears cache).
        
        Args:
            config_path: Relative path from config root
        
        Returns:
            Reloaded configuration
        """
        logger.info(f"Reloading config: {config_path}")
        self._cache.pop(config_path, None)
        return self.load(config_path)
    
    def _expand_env_vars(self, obj: Any) -> Any:
        """
        Recursively expand environment variables in config.
        
        Supports:
        - ${VAR:default} - env var with default value
        - ${VAR} - env var (raises if not set)
        
        Args:
            obj: Config value (dict, list, str, etc.)
        
        Returns:
            Expanded value
        """
        if isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        
        elif isinstance(obj, str):
            # Check for ${VAR} or ${VAR:default} pattern
            if obj.startswith('${') and obj.endswith('}'):
                var_spec = obj[2:-1]  # Remove ${ and }
                
                if ':' in var_spec:
                    # ${VAR:default} format
                    var_name, default = var_spec.split(':', 1)
                    return os.getenv(var_name, default)
                else:
                    # ${VAR} format - must exist
                    var_name = var_spec
                    value = os.getenv(var_name)
                    if value is None:
                        raise ValueError(f"Environment variable not set: {var_name}")
                    return value
            
            return obj
        
        else:
            # Primitives (int, float, bool, None)
            return obj
    
    def clear_cache(self):
        """Clear all cached configs."""
        self._cache.clear()
        logger.info("Config cache cleared")
    
    def get_cached_files(self) -> list:
        """Get list of cached config files."""
        return list(self._cache.keys())


# Global singleton instance
config_loader = ConfigLoader()
