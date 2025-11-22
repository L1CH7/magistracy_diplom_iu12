"""Config bridge for JS-to-Python config access via QWebChannel."""
import json
from PyQt5.QtCore import QObject, pyqtSlot
from src.utils.config_loader import config_loader


class ConfigBridge(QObject):
    """Bridge for accessing Python config from JavaScript."""

    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        self._map_config = None  # Lazy load

    @pyqtSlot(result=bool)
    def isDebugEnabled(self) -> bool:
        """Check if debug mode is enabled."""
        return self._config.get('debug', {}).get('enabled', False)

    @pyqtSlot(result=str)
    def getMapConfig(self) -> str:
        """
        Get map configuration (LOD layers, rendering, etc.) as JSON.
        Loads from configs/client/map.yaml (includes lod + rendering).
        """
        if self._map_config is None:
            try:
                self._map_config = config_loader.load('client/map.yaml')
            except Exception as e:
                print(f"[ConfigBridge] Failed to load map.yaml: {e}")
                # Fallback to empty config
                self._map_config = {"lod": {"layers": []}, "rendering": {}}
        
        return json.dumps(self._map_config)
