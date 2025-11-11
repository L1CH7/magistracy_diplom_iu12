from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QPushButton, QLabel, QTextEdit, QWidget
)
from .collapsible import CollapsibleSection
from .selected_points_widget import SelectedPointsWidget
from .route_panel import RoutePanel
from .simulation_panel import SimulationPanel

class SidebarWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; }"
        )
        self.setMaximumWidth(350)
        self.setMinimumWidth(280)
        self.setMinimumHeight(600)
        sidebar_layout = QVBoxLayout(self)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

        # Get Road Graph Data button (no emoji)
        self.get_road_graph_btn = QPushButton("Get Road Graph Data")
        self.get_road_graph_btn.setStyleSheet(
            "QPushButton { background-color: #8b5cf6; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #7c3aed; }"
        )
        sidebar_layout.addWidget(self.get_road_graph_btn)

        # Route panel for K routes display
        self.route_panel = RoutePanel()
        sidebar_layout.addWidget(self.route_panel)
        
        # Simulation panel for agent control
        self.simulation_panel = SimulationPanel()
        sidebar_layout.addWidget(self.simulation_panel)

        self.points_section = CollapsibleSection("Selected Points")
        self.selected_points_widget = SelectedPointsWidget()
        self.points_section.add_widget(self.selected_points_widget)
        sidebar_layout.addWidget(self.points_section)

        sidebar_layout.addStretch()
        self.quit_btn = QPushButton("Quit (ESC)")
        self.quit_btn.setStyleSheet("QPushButton { background-color: #ef4444; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #dc2626; }")
        sidebar_layout.addWidget(self.quit_btn)
