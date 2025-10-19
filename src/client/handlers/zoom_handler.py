"""Zoom level control handler."""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QSlider
from PyQt5.QtCore import Qt, pyqtSlot

# Handle both relative and absolute imports
try:
    from ..models import NavigationState
except ImportError:
    from models import NavigationState


class ZoomControl(QWidget):
    """Zoom control with slider."""

    def __init__(self, nav_state: NavigationState, parent=None):
        super().__init__(parent)
        self.nav_state = nav_state
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Setup zoom slider."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMaximum(18)
        self.slider.setValue(12)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(1)

        layout.addWidget(self.slider)

    def _connect_signals(self):
        """Connect slider to nav_state signals."""
        self.slider.sliderMoved.connect(self._on_slider_changed)
        self.nav_state.zoom_changed.connect(self._on_zoom_changed)

    @pyqtSlot(int)
    def _on_slider_changed(self, value: int):
        """Handle slider movement."""
        self.nav_state.set_zoom(value)

    @pyqtSlot(int)
    def _on_zoom_changed(self, zoom: int):
        """Update slider when nav_state zoom changes."""
        if self.slider.value() != zoom:
            self.slider.blockSignals(True)
            self.slider.setValue(zoom)
            self.slider.blockSignals(False)

    def get_zoom(self) -> int:
        """Get current zoom level."""
        return self.nav_state.zoom
