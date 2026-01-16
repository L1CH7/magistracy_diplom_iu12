"""Status panel with logs and route information."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit
from PyQt5.QtCore import pyqtSlot

from ...models import NavigationState
from .collapsible_section import CollapsibleSection


class StatusPanel(QWidget):
    """Panel displaying route information, status, and logs.
    
    Contains collapsible sections for:
    - Route information
    - Agent status logs
    - Speed information
    
    Listens to NavigationState signals.
    """

    def __init__(self, state: NavigationState, parent: QWidget = None):
        """Initialize status panel.
        
        Args:
            state: NavigationState object
            parent: Parent widget
        """
        super().__init__(parent)
        self.state = state
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # === ROUTE SECTION ===
        self.route_text = QTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setMaximumHeight(100)
        self.route_text.setStyleSheet(
            "QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; "
            "background-color: #f9fafb; font-size: 9px; "
            "font-family: monospace; }"
        )
        
        self.route_section = CollapsibleSection("Route Info")
        self.route_section.add_widget(self.route_text)
        layout.addWidget(self.route_section)
        
        # === STATUS SECTION ===
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.setStyleSheet(
            "QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; "
            "background-color: #f9fafb; font-size: 9px; "
            "font-family: monospace; }"
        )
        
        self.status_section = CollapsibleSection("Status & Logs")
        self.status_section.add_widget(self.status_text)
        layout.addWidget(self.status_section)
        
        # === SPEED SECTION ===
        self.speed_label = QLabel("Speed: —")
        self.speed_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #2563eb; padding: 4px;"
        )
        
        self.speed_section = CollapsibleSection("Performance")
        self.speed_section.add_widget(self.speed_label)
        layout.addWidget(self.speed_section)
        
        # === MAP BOUNDS ===
        self.bounds_label = QLabel("Bounds: [−, −, −, −]")
        self.bounds_label.setStyleSheet(
            "font-family: monospace; font-size: 9px; color: #6b7280; "
            "padding: 4px;"
        )
        layout.addWidget(self.bounds_label)
        
        # Connect to state signals
        self.state.status_changed.connect(self._on_status_changed)
        self.state.error_occurred.connect(self._on_error)
        self.state.route_updated.connect(self._on_route_updated)
        self.state.bounds_changed.connect(self._on_bounds_changed)
        
        layout.addStretch()
    
    @pyqtSlot(str)
    def _on_status_changed(self, status: str) -> None:
        """Handle status changed signal.
        
        Args:
            status: Status message
        """
        self.status_text.append(f"[STATUS] {status}")
    
    @pyqtSlot(str)
    def _on_error(self, error: str) -> None:
        """Handle error signal.
        
        Args:
            error: Error message
        """
        self.status_text.append(f"[ERROR] {error}")
    
    @pyqtSlot(object)
    def _on_route_updated(self, route) -> None:
        """Handle route updated signal.
        
        Args:
            route: Route object
        """
        self.route_text.clear()
        distance_km = route.get_distance_km()
        duration_min = route.get_duration_minutes()
        nodes_count = len(route.nodes)
        
        info = (
            f"Nodes: {nodes_count}\n"
            f"Distance: {distance_km:.2f} km\n"
            f"Duration: {duration_min:.1f} min\n"
            f"Edges: {len(route.edges)}"
        )
        self.route_text.setText(info)
    
    @pyqtSlot(tuple)
    def _on_bounds_changed(self, bounds: tuple) -> None:
        """Handle bounds changed signal.
        
        Args:
            bounds: (minLon, minLat, maxLon, maxLat)
        """
        if bounds:
            min_lon, min_lat, max_lon, max_lat = bounds
            self.bounds_label.setText(
                f"Bounds: [{min_lon:.4f}, {min_lat:.4f}, "
                f"{max_lon:.4f}, {max_lat:.4f}]"
            )
    
    def append_log(self, message: str) -> None:
        """Append message to status log.
        
        Args:
            message: Message to append
        """
        self.status_text.append(message)
    
    def update_speed(self, speed_kmh: float) -> None:
        """Update speed display.
        
        Args:
            speed_kmh: Speed in km/h
        """
        self.speed_label.setText(f"Speed: {speed_kmh:.1f} km/h")
    
    def clear_logs(self) -> None:
        """Clear all log text."""
        self.status_text.clear()
        self.route_text.clear()
