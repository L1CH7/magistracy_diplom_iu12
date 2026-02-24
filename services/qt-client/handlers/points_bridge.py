"""Points bridge: Qt bridge for JS-to-Python points communication."""
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal


class PointsBridge(QObject):
    """Bridge between JS map and Python points widget via Qt signals."""
    
    points_changed = pyqtSignal()
    
    @pyqtSlot()
    def notify_points_changed(self) -> None:
        """Called from JS when points are added/removed/moved.
        
        Emits points_changed signal to update Python UI.
        """
        self.points_changed.emit()
