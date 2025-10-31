"""Zoom bridge: Qt bridge for JS-to-Python zoom communication."""
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal


class ZoomBridge(QObject):
    """Bridge between JS map and Python zoom controls via Qt signals."""
    
    zoom_changed = pyqtSignal(int)
    
    @pyqtSlot(int)
    def notify_zoom(self, zoom: int) -> None:
        """Called from JS when map zoom changes.
        
        Args:
            zoom: Current map zoom level
        """
        self.zoom_changed.emit(zoom)
