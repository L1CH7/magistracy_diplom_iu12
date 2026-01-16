"""Points panel for displaying and managing navigation points."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame
)
from PyQt5.QtCore import pyqtSlot

from ...models import Point, NavigationState


class PointsPanel(QWidget):
    """Panel for displaying and managing navigation points.
    
    Displays current points as "tiles" with:
    - Point type (Start/End/Via N)
    - Coordinates
    - Delete button
    - Move buttons (↑↓) to reorder
    
    Listens to NavigationState.points_changed signal.
    """

    def __init__(self, state: NavigationState, parent: QWidget = None):
        """Initialize points panel.
        
        Args:
            state: NavigationState object
            parent: Parent widget
        """
        super().__init__(parent)
        self.state = state
        self.point_widgets = []
        
        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(6)
        
        # Connect to state signals
        self.state.points_changed.connect(self._on_points_changed)
        
        # Initial render
        self._render_points()
    
    @pyqtSlot(list)
    def _on_points_changed(self, points):
        """Handle points changed signal.
        
        Args:
            points: List of Point objects
        """
        self._render_points()
    
    def _render_points(self):
        """Render current points."""
        # Clear old widgets
        for widget in self.point_widgets:
            self.main_layout.removeWidget(widget)
            widget.deleteLater()
        self.point_widgets.clear()
        
        points = self.state.get_points()
        
        if not points:
            # Show empty state
            empty = QLabel("No points selected")
            empty.setStyleSheet("color: #9ca3af; font-style: italic;")
            self.main_layout.addWidget(empty)
            self.point_widgets.append(empty)
            self.main_layout.addStretch()
            return
        
        # Render each point as a tile
        for idx, point in enumerate(points):
            tile = self._create_point_tile(idx, point)
            self.main_layout.addWidget(tile)
            self.point_widgets.append(tile)
        
        self.main_layout.addStretch()
    
    def _create_point_tile(self, idx: int, point: Point) -> QFrame:
        """Create a point display tile.
        
        Args:
            idx: Point index
            point: Point object
        
        Returns:
            QFrame with point display and controls
        """
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: #f3f4f6; border: 1px solid #e5e7eb; "
            "border-radius: 6px; } "
            "QFrame:hover { background-color: #f9fafb; }"
        )
        frame.setMinimumHeight(60)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        
        # Left: Color indicator + info
        info_layout = QVBoxLayout()
        
        # Type + label
        type_label = QLabel(f"{point.label}")
        type_label.setStyleSheet("font-weight: bold; color: #1f2937;")
        info_layout.addWidget(type_label)
        
        # Coordinates
        coords_label = QLabel(f"{point.lon:.4f}, {point.lat:.4f}")
        coords_label.setStyleSheet(
            "font-family: monospace; font-size: 9px; color: #6b7280;"
        )
        info_layout.addWidget(coords_label)
        info_layout.addStretch()
        
        # Color indicator
        color_box = QFrame()
        color_box.setStyleSheet(
            f"QFrame {{ background-color: {point.color}; "
            "border-radius: 3px; }}"
        )
        color_box.setMaximumHeight(16)
        color_box.setMaximumWidth(16)
        
        info_row = QHBoxLayout()
        info_row.addWidget(color_box)
        info_row.addLayout(info_layout)
        layout.addLayout(info_row, 1)
        
        # Right: Controls
        controls_layout = QVBoxLayout()
        
        # Up/Down buttons
        if len(self.state.get_points()) > 1:
            move_layout = QHBoxLayout()
            
            if idx > 0:
                up_btn = QPushButton("↑")
                up_btn.setMaximumWidth(30)
                up_btn.clicked.connect(lambda: self._move_point(idx, -1))
                move_layout.addWidget(up_btn)
            
            if idx < len(self.state.get_points()) - 1:
                down_btn = QPushButton("↓")
                down_btn.setMaximumWidth(30)
                down_btn.clicked.connect(lambda: self._move_point(idx, 1))
                move_layout.addWidget(down_btn)
            
            if move_layout.count() > 0:
                controls_layout.addLayout(move_layout)
        
        # Delete button
        del_btn = QPushButton("✕")
        del_btn.setMaximumWidth(30)
        del_btn.setStyleSheet(
            "QPushButton { background-color: #f87171; color: white; "
            "border: none; border-radius: 3px; } "
            "QPushButton:hover { background-color: #ef4444; }"
        )
        del_btn.clicked.connect(lambda: self._remove_point(idx))
        controls_layout.addWidget(del_btn)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout, 0)
        
        return frame
    
    def _remove_point(self, idx: int) -> None:
        """Remove point by index.
        
        Args:
            idx: Point index
        """
        self.state.remove_point(idx)
    
    def _move_point(self, idx: int, direction: int) -> None:
        """Move point up/down.
        
        Args:
            idx: Current index
            direction: -1 for up, 1 for down
        """
        self.state.move_point(idx, direction)
