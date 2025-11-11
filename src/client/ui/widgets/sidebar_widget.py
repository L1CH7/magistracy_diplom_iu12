from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QPushButton, QLabel, QTextEdit, QWidget
)
from .collapsible import CollapsibleSection
from .selected_points_widget import SelectedPointsWidget
from .route_panel import RoutePanel

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

        # Title (no close button - it's outside now)
        # Get Road Graph Data button
        self.get_road_graph_btn = QPushButton("🗺️ Get Road Graph Data")
        self.get_road_graph_btn.setStyleSheet(
            "QPushButton { background-color: #8b5cf6; color: white; "
            "border: none; border-radius: 6px; padding: 8px; "
            "font-weight: bold; } "
            "QPushButton:hover { background-color: #7c3aed; }"
        )
        sidebar_layout.addWidget(self.get_road_graph_btn)
        
        # Agent control buttons
        btn_layout = QVBoxLayout()
        self.start_agent_btn = QPushButton("Start Agent")
        self.start_agent_btn.setEnabled(False)
        self.start_agent_btn.setStyleSheet("QPushButton { background-color: #10b981; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #059669; } QPushButton:disabled { background-color: #d1d5db; }")
        btn_layout.addWidget(self.start_agent_btn)
        self.restart_btn = QPushButton("Restart Agent")
        self.restart_btn.setEnabled(False)
        self.restart_btn.setStyleSheet("QPushButton { background-color: #f59e0b; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #d97706; } QPushButton:disabled { background-color: #d1d5db; }")
        btn_layout.addWidget(self.restart_btn)
        sidebar_layout.addLayout(btn_layout)

        # Route panel for K routes display
        self.route_panel = RoutePanel()
        sidebar_layout.addWidget(self.route_panel)

        bounds_layout = QVBoxLayout()
        bounds_layout.addWidget(QLabel("Map bounds:"))
        self.bounds_label = QLabel("[-, -, -, -]")
        self.bounds_label.setStyleSheet("font-family: monospace; font-size: 10px; color: #6b7280;")
        bounds_layout.addWidget(self.bounds_label)
        sidebar_layout.addLayout(bounds_layout)

        self.route_text = QTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setStyleSheet("QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; background-color: #f9fafb; font-size: 10px; }")
        self.route_section = CollapsibleSection("Route")
        self.route_section.add_widget(self.route_text)
        sidebar_layout.addWidget(self.route_section)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; background-color: #f9fafb; font-size: 10px; }")
        self.status_section = CollapsibleSection("Agent Status")
        self.status_section.add_widget(self.status_text)
        sidebar_layout.addWidget(self.status_section)

        self.speed_label = QLabel("Speed: 0 km/h")
        self.speed_label.setStyleSheet("font-weight: bold; color: #2563eb;")
        self.speed_section = CollapsibleSection("Speed")
        self.speed_section.add_widget(self.speed_label)
        sidebar_layout.addWidget(self.speed_section)

        self.points_section = CollapsibleSection("Selected Points")
        self.selected_points_widget = SelectedPointsWidget()
        self.points_section.add_widget(self.selected_points_widget)
        sidebar_layout.addWidget(self.points_section)

        sidebar_layout.addStretch()
        self.quit_btn = QPushButton("Quit (ESC)")
        self.quit_btn.setStyleSheet("QPushButton { background-color: #ef4444; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #dc2626; }")
        sidebar_layout.addWidget(self.quit_btn)
