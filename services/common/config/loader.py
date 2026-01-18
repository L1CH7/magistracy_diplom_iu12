"""
Configuration loader with hot reload support for YAML configs.

Features:
- YAML loading with !include directive (via pyyaml-include if available)
- Caching for performance
- Environment variable expansion: ${VAR:default}
- Hot reload via reload() method
- Auto-detects /app/configs (container) or project configs/ (dev)
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict
from loguru import logger
import yaml_include

# Config: custom directive name for includes
INCLUDE_DIRECTIVE = '!include'


class ConfigLoader:
    """Manages YAML configuration loading with caching and hot reload."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._config_root = self._detect_config_root()
        logger.info(f"ConfigLoader initialized with root: {self._config_root}")
    
    def _detect_config_root(self) -> Path:
        """Detect config root directory (container or dev environment)."""
        # (detection logic unchanged)
        # Try container path first
        container_path = Path('/app/configs')
        if container_path.exists():
            return container_path
        
        # Try CWD (project root)
        cwd_path = Path(os.getcwd()) / 'configs'
        if cwd_path.exists():
            return cwd_path
            
        # Try relative to this file (services.common.config.py -> ROOT/configs)
        # parent = utils, parent.parent = common, parent.parent.parent = services, parent.parent.parent.parent = ROOT
        file_relative_path = Path(__file__).parent.parent.parent.parent / 'configs'
        if file_relative_path.exists():
            return file_relative_path
        
        raise FileNotFoundError(
            f"Config directory not found. Tried:\n"
            f"  - {container_path}\n"
            f"  - {cwd_path}\n"
            f"  - {file_relative_path}"
        )

    def set_config_root(self, path: str) -> None:
        """
        Manually set configuration root directory.
        
        Args:
            path: Absolute or relative path to config directory
        """
        new_root = Path(path).resolve()
        if not new_root.exists():
            raise FileNotFoundError(f"Config root not found: {new_root}")
            
        self._config_root = new_root
        self._cache.clear()  # Clear cache as paths might change
        logger.info(f"Config root manually set to: {self._config_root}")

    
    def load(self, config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file with !include support.
        
        Args:
            config_path: Relative path from config root
        
        Returns:
            Parsed configuration dictionary
        """
        # Check cache first
        if config_path in self._cache:
            return self._cache[config_path]
        
        # Load from file
        full_path = self._config_root / config_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_path}")
        
        logger.debug(f"Loading config: {config_path}")
        
        # Read file content
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if includes are used
        if INCLUDE_DIRECTIVE in content:
            # Use pyyaml-include
            # yaml_include.Constructor is the class we need
            
            # Create a constructor for the specific base directory
            include_constructor = yaml_include.Constructor(base_dir=str(full_path.parent))
            
            # Create a custom loader class inheriting from FullLoader
            class Loader(yaml.FullLoader):
                pass
            
            yaml.add_constructor(INCLUDE_DIRECTIVE, include_constructor, Loader)
            
            with open(full_path, 'r', encoding='utf-8') as f:
                config = yaml.load(f, Loader)
        else:
            # Plain YAML
            config = yaml.safe_load(content)
        
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
                        raise ValueError(
                            f"Environment variable not set: {var_name}"
                        )
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

def load_config(config_path: str) -> Dict[str, Any]:
    """Helper for backward compatibility."""
    return config_loader.load(config_path)
