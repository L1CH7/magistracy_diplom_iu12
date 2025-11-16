"""Config bridge for JS-to-Python config access via QWebChannel."""
from PyQt5.QtCore import QObject, pyqtSlot


class ConfigBridge(QObject):
    """Bridge for accessing Python config from JavaScript."""

    def __init__(self, config: dict):
        super().__init__()
        self._config = config

    @pyqtSlot(result=bool)
    def isDebugEnabled(self) -> bool:
        """Check if debug mode is enabled."""
        return self._config.get('debug', {}).get('enabled', False)
