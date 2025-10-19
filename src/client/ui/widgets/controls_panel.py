"""Controls panel with input fields and action buttons."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QSpinBox
)
from PyQt5.QtCore import pyqtSignal

from ...models import NavigationState


class ControlsPanel(QWidget):
    """Panel with controls: coordinate inputs, K routes, action buttons.
    
    Signals:
    - load_graph_clicked: Load graph button pressed
    - calculate_route_clicked: Calculate route button pressed
    - start_agent_clicked: Start agent button pressed
    - restart_agent_clicked: Restart agent button pressed
    - clear_clicked: Clear points button pressed
    """

    # Signals
    load_graph_clicked = pyqtSignal()
    calculate_route_clicked = pyqtSignal()
    start_agent_clicked = pyqtSignal()
    restart_agent_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()

    def __init__(self, state: NavigationState, parent: QWidget = None):
        """Initialize controls panel.
        
        Args:
            state: NavigationState object
            parent: Parent widget
        """
        super().__init__(parent)
        self.state = state
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # === COORDINATES INPUT ===
        layout.addWidget(QLabel("Waypoints"))
        
        # Start coordinates
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("Start:"))
        
        self.start_lon_input = QLineEdit("37.618423")
        self.start_lon_input.setPlaceholderText("lon")
        self.start_lon_input.setMaximumWidth(90)
        start_layout.addWidget(self.start_lon_input)
        
        self.start_lat_input = QLineEdit("55.751244")
        self.start_lat_input.setPlaceholderText("lat")
        self.start_lat_input.setMaximumWidth(90)
        start_layout.addWidget(self.start_lat_input)
        
        layout.addLayout(start_layout)
        
        # End coordinates
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("End:"))
        
        self.end_lon_input = QLineEdit("37.617300")
        self.end_lon_input.setPlaceholderText("lon")
        self.end_lon_input.setMaximumWidth(90)
        end_layout.addWidget(self.end_lon_input)
        
        self.end_lat_input = QLineEdit("55.755826")
        self.end_lat_input.setPlaceholderText("lat")
        self.end_lat_input.setMaximumWidth(90)
        end_layout.addWidget(self.end_lat_input)
        
        layout.addLayout(end_layout)
        
        # K routes
        k_layout = QHBoxLayout()
        k_layout.addWidget(QLabel("K routes:"))
        self.k_spinbox = QSpinBox()
        self.k_spinbox.setMinimum(1)
        self.k_spinbox.setMaximum(10)
        self.k_spinbox.setValue(1)
        self.k_spinbox.setMaximumWidth(60)
        k_layout.addWidget(self.k_spinbox)
        k_layout.addStretch()
        layout.addLayout(k_layout)
        
        # === BUTTONS ===
        layout.addWidget(QLabel("Actions"))
        
        # Load graph button
        self.load_graph_btn = QPushButton("📥 Load Graph")
        self.load_graph_btn.setStyleSheet(
            "QPushButton { background-color: #8b5cf6; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #7c3aed; } "
            "QPushButton:pressed { background-color: #6d28d9; }"
        )
        self.load_graph_btn.clicked.connect(self.load_graph_clicked.emit)
        layout.addWidget(self.load_graph_btn)
        
        # Calculate route button
        self.calc_route_btn = QPushButton("🚀 Calculate Route")
        self.calc_route_btn.setStyleSheet(
            "QPushButton { background-color: #3b82f6; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #2563eb; } "
            "QPushButton:pressed { background-color: #1d4ed8; }"
        )
        self.calc_route_btn.clicked.connect(
            self.calculate_route_clicked.emit
        )
        layout.addWidget(self.calc_route_btn)
        
        # Start agent button
        self.start_agent_btn = QPushButton("▶ Start Agent")
        self.start_agent_btn.setEnabled(False)
        self.start_agent_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #059669; } "
            "QPushButton:pressed { background-color: #047857; } "
            "QPushButton:disabled { background-color: #d1d5db; }"
        )
        self.start_agent_btn.clicked.connect(self.start_agent_clicked.emit)
        layout.addWidget(self.start_agent_btn)
        
        # Restart agent button
        self.restart_agent_btn = QPushButton("⟲ Restart Agent")
        self.restart_agent_btn.setEnabled(False)
        self.restart_agent_btn.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #d97706; } "
            "QPushButton:pressed { background-color: #b45309; } "
            "QPushButton:disabled { background-color: #d1d5db; }"
        )
        self.restart_agent_btn.clicked.connect(
            self.restart_agent_clicked.emit
        )
        layout.addWidget(self.restart_agent_btn)
        
        # Clear button
        self.clear_btn = QPushButton("🗑 Clear Points")
        self.clear_btn.setStyleSheet(
            "QPushButton { background-color: #ef4444; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #dc2626; } "
            "QPushButton:pressed { background-color: #b91c1c; }"
        )
        self.clear_btn.clicked.connect(self.clear_clicked.emit)
        layout.addWidget(self.clear_btn)
        
        layout.addStretch()
    
    def get_start_coords(self):
        """Get start coordinates as (lon, lat) tuple."""
        try:
            lon = float(self.start_lon_input.text())
            lat = float(self.start_lat_input.text())
            return (lon, lat)
        except ValueError:
            return None
    
    def get_end_coords(self):
        """Get end coordinates as (lon, lat) tuple."""
        try:
            lon = float(self.end_lon_input.text())
            lat = float(self.end_lat_input.text())
            return (lon, lat)
        except ValueError:
            return None
    
    def get_k_routes(self) -> int:
        """Get K routes value."""
        return self.k_spinbox.value()
    
    def set_start_coords(self, lon: float, lat: float) -> None:
        """Set start coordinates.
        
        Args:
            lon: Longitude
            lat: Latitude
        """
        self.start_lon_input.setText(f"{lon:.6f}")
        self.start_lat_input.setText(f"{lat:.6f}")
    
    def set_end_coords(self, lon: float, lat: float) -> None:
        """Set end coordinates.
        
        Args:
            lon: Longitude
            lat: Latitude
        """
        self.end_lon_input.setText(f"{lon:.6f}")
        self.end_lat_input.setText(f"{lat:.6f}")
    
    def enable_agent_buttons(self, enabled: bool = True) -> None:
        """Enable/disable agent control buttons.
        
        Args:
            enabled: True to enable, False to disable
        """
        self.start_agent_btn.setEnabled(enabled)
        self.restart_agent_btn.setEnabled(enabled)
