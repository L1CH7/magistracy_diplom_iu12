"""
Routing panel with K routes selector and route list.

This panel displays:
- K routes slider
- "Get Routes" button
- List of found routes with metrics
- Route selection
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QListWidget, QListWidgetItem, QGroupBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QFont

from src.utils.logger import setup_logger


log = setup_logger(__name__)


class RoutePanel(QWidget):
    """
    Panel for route configuration and display.

    Signals:
        get_routes_clicked: User clicked "Get Routes" button
        route_selected: User selected a route (route_id)
    """

    # Signals
    get_routes_clicked = pyqtSignal(int)  # k value
    route_selected = pyqtSignal(int)  # route_id

    def __init__(self, parent: QWidget = None):
        """Initialize routing panel."""
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # === K ROUTES SELECTOR ===
        k_group = QGroupBox("Route Options")
        k_layout = QVBoxLayout(k_group)

        # K routes spinbox
        k_row = QHBoxLayout()
        k_row.addWidget(QLabel("Number of routes:"))

        self.k_spinbox = QSpinBox()
        self.k_spinbox.setRange(1, 10)
        self.k_spinbox.setValue(5)
        self.k_spinbox.setMaximumWidth(60)
        k_row.addWidget(self.k_spinbox)
        k_row.addStretch()

        k_layout.addLayout(k_row)

        # Get Routes button
        self.get_routes_btn = QPushButton("🗺️ Get Routes")
        self.get_routes_btn.setStyleSheet(
            "QPushButton { "
            "background-color: #10b981; "
            "color: white; "
            "border: none; "
            "border-radius: 6px; "
            "padding: 10px; "
            "font-weight: bold; "
            "font-size: 14px; "
            "} "
            "QPushButton:hover { "
            "background-color: #059669; "
            "} "
            "QPushButton:pressed { "
            "background-color: #047857; "
            "} "
            "QPushButton:disabled { "
            "background-color: #d1d5db; "
            "color: #9ca3af; "
            "}"
        )
        self.get_routes_btn.clicked.connect(self._on_get_routes_clicked)
        k_layout.addWidget(self.get_routes_btn)

        layout.addWidget(k_group)

        # === ROUTES LIST ===
        routes_group = QGroupBox("Found Routes")
        routes_layout = QVBoxLayout(routes_group)

        # Status label
        self.status_label = QLabel("No routes found yet")
        self.status_label.setStyleSheet(
            "color: #6b7280; font-style: italic; padding: 8px;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        routes_layout.addWidget(self.status_label)

        # Routes list widget
        self.routes_list = QListWidget()
        self.routes_list.setMaximumHeight(300)
        self.routes_list.setStyleSheet(
            "QListWidget { "
            "border: 1px solid #d1d5db; "
            "border-radius: 6px; "
            "background-color: white; "
            "} "
            "QListWidget::item { "
            "padding: 10px; "
            "border-bottom: 1px solid #f3f4f6; "
            "} "
            "QListWidget::item:selected { "
            "background-color: #dbeafe; "
            "color: #1e40af; "
            "} "
            "QListWidget::item:hover { "
            "background-color: #f3f4f6; "
            "}"
        )
        self.routes_list.itemClicked.connect(self._on_route_item_clicked)
        routes_layout.addWidget(self.routes_list)

        layout.addWidget(routes_group)

        layout.addStretch()

        # Store current routes data
        self.routes_data = []

    def _on_get_routes_clicked(self):
        """Handle Get Routes button click."""
        k = self.k_spinbox.value()
        log.info("Get routes clicked", k=k)
        self.get_routes_clicked.emit(k)

    def _on_route_item_clicked(self, item: QListWidgetItem):
        """Handle route item click."""
        route_id = item.data(Qt.UserRole)
        if route_id is not None:
            log.info("Route selected", route_id=route_id)
            self.route_selected.emit(route_id)

    def display_routes(self, routes: list):
        """
        Display routes in the list.

        Args:
            routes: List of route dicts with keys:
                - id: Route ID (int)
                - edges: List of edge IDs
                - total_distance_m: Total distance in meters
                - total_time_sec: Total time in seconds
                - geometry: List of (lon, lat) coordinates
        """
        self.routes_data = routes
        self.routes_list.clear()

        if not routes:
            self.status_label.setText("No routes found")
            self.status_label.show()
            self.routes_list.hide()
            return

        self.status_label.hide()
        self.routes_list.show()

        for route in routes:
            route_id = route['id']
            distance_m = route['total_distance_m']
            time_sec = route['total_time_sec']
            num_edges = len(route['edges'])

            # Format distance
            if distance_m < 1000:
                distance_str = f"{distance_m:.0f} m"
            else:
                distance_str = f"{distance_m / 1000:.2f} km"

            # Format time
            if time_sec < 60:
                time_str = f"{time_sec:.0f} sec"
            else:
                minutes = int(time_sec / 60)
                seconds = int(time_sec % 60)
                time_str = f"{minutes} min {seconds} sec"

            # Create item text
            item_text = f"Route {route_id + 1}\n"
            item_text += f"📏 {distance_str}  ⏱️ {time_str}\n"
            item_text += f"🛣️ {num_edges} edges"

            # Create list item
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, route_id)

            # Style first route (best) differently
            if route_id == 0:
                font = QFont()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(Qt.darkGreen)

            self.routes_list.addItem(item)

        # Select first route by default
        self.routes_list.setCurrentRow(0)

        log.info("Routes displayed", num_routes=len(routes))

    def clear_routes(self):
        """Clear routes list."""
        self.routes_list.clear()
        self.routes_data = []
        self.status_label.setText("No routes found yet")
        self.status_label.show()
        self.routes_list.hide()
        log.debug("Routes cleared")

    def get_k_value(self) -> int:
        """Get current K value from spinbox."""
        return self.k_spinbox.value()

    def set_loading(self, loading: bool):
        """
        Set loading state for Get Routes button.

        Args:
            loading: True if loading, False otherwise
        """
        if loading:
            self.get_routes_btn.setEnabled(False)
            self.get_routes_btn.setText("⏳ Loading...")
        else:
            self.get_routes_btn.setEnabled(True)
            self.get_routes_btn.setText("🗺️ Get Routes")
