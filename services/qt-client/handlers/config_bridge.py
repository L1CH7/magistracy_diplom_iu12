"""Config bridge for JS-to-Python config access via QWebChannel."""
import json
from PyQt5.QtCore import QObject, pyqtSlot
from services.common.config import config_loader
from loguru import logger as log


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
                log.info("[ConfigBridge] Map config loaded:")
                lod_keys = list(self._map_config.get('lod', {}).keys())
                rendering_keys = list(
                    self._map_config.get('rendering', {}).keys()
                )
                log.info(f"  - lod: {lod_keys}")
                log.info(f"  - rendering: {rendering_keys}")
                log.info(f"  - routes: {'routes' in self._map_config}")
                log.info(f"  - k_routes: {'k_routes' in self._map_config}")
                
                # Debug: print LOD layers
                lod_layers = self._map_config.get('lod', {}).get('layers', [])
                log.trace(f"  - LOD layers count: {len(lod_layers)}")
                for i, layer in enumerate(lod_layers):
                    name = layer.get('name')
                    minz = layer.get('minzoom')
                    maxz = layer.get('maxzoom')
                    highways = layer.get('highways', [])
                    log.trace(
                        f"    Layer {i}: {name} (zoom {minz}-{maxz}), "
                        f"{len(highways)} highways"
                    )
            except Exception as e:
                log.error(f"[ConfigBridge] Failed to load map.yaml: {e}")
                # Fallback to empty config
                self._map_config = {"lod": {"layers": []}, "rendering": {}}
        
        # Inject apiBaseUrl from GUI config (passed via constructor)
        if 'apiBaseUrl' in self._config:
            self._map_config['apiBaseUrl'] = self._config['apiBaseUrl']
            
        return json.dumps(self._map_config)
