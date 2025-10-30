from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QWidget
)
from .collapsible import CollapsibleSection
from .selected_points_widget import SelectedPointsWidget

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

        # Top bar with close/open button
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_close_btn = QPushButton("☰")
        self.sidebar_close_btn.setMaximumWidth(40)
        self.sidebar_close_btn.setMaximumHeight(40)
        self.sidebar_close_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 18px; } QPushButton:hover { background-color: #1d4ed8; }"
        )
        top_bar_layout.addWidget(self.sidebar_close_btn)
        top_bar_layout.addStretch()
        sidebar_layout.addLayout(top_bar_layout)

        self.sidebar_visible = True
        self.sidebar_open_btn = QPushButton("☰")
        self.sidebar_open_btn.setMaximumWidth(40)
        self.sidebar_open_btn.setMaximumHeight(40)
        self.sidebar_open_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 18px; } QPushButton:hover { background-color: #1d4ed8; }"
        )

        title_label = QLabel("Navigation")
        title_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #1f2937;")
        sidebar_layout.addWidget(title_label)

        # Start/End coords
        start_frame = QHBoxLayout()
        start_frame.addWidget(QLabel("Start Lat:"))
        self.start_lat = QLineEdit("55.751244")
        self.start_lat.setStyleSheet("QLineEdit { border-radius: 4px; padding: 4px; border: 1px solid #d1d5db; }")
        start_frame.addWidget(self.start_lat)
        sidebar_layout.addLayout(start_frame)

        start_frame2 = QHBoxLayout()
        start_frame2.addWidget(QLabel("Start Lon:"))
        self.start_lon = QLineEdit("37.618423")
        self.start_lon.setStyleSheet("QLineEdit { border-radius: 4px; padding: 4px; border: 1px solid #d1d5db; }")
        start_frame2.addWidget(self.start_lon)
        sidebar_layout.addLayout(start_frame2)

        end_frame = QHBoxLayout()
        end_frame.addWidget(QLabel("End Lat:"))
        self.end_lat = QLineEdit("55.755826")
        self.end_lat.setStyleSheet("QLineEdit { border-radius: 4px; padding: 4px; border: 1px solid #d1d5db; }")
        end_frame.addWidget(self.end_lat)
        sidebar_layout.addLayout(end_frame)

        end_frame2 = QHBoxLayout()
        end_frame2.addWidget(QLabel("End Lon:"))
        self.end_lon = QLineEdit("37.617300")
        self.end_lon.setStyleSheet("QLineEdit { border-radius: 4px; padding: 4px; border: 1px solid #d1d5db; }")
        end_frame2.addWidget(self.end_lon)
        sidebar_layout.addLayout(end_frame2)

        k_frame = QHBoxLayout()
        k_frame.addWidget(QLabel("K routes:"))
        self.k_entry = QLineEdit("1")
        self.k_entry.setStyleSheet("QLineEdit { border-radius: 4px; padding: 4px; border: 1px solid #d1d5db; }")
        k_frame.addWidget(self.k_entry)
        sidebar_layout.addLayout(k_frame)

        btn_layout = QVBoxLayout()
        self.get_route_btn = QPushButton("Get Route")
        self.get_route_btn.setStyleSheet("QPushButton { background-color: #3b82f6; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #2563eb; }")
        btn_layout.addWidget(self.get_route_btn)
        self.start_agent_btn = QPushButton("Start Agent")
        self.start_agent_btn.setEnabled(False)
        self.start_agent_btn.setStyleSheet("QPushButton { background-color: #10b981; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #059669; } QPushButton:disabled { background-color: #d1d5db; }")
        btn_layout.addWidget(self.start_agent_btn)
        self.restart_btn = QPushButton("Restart Agent")
        self.restart_btn.setEnabled(False)
        self.restart_btn.setStyleSheet("QPushButton { background-color: #f59e0b; color: white; border: none; border-radius: 6px; padding: 8px; font-weight: bold; } QPushButton:hover { background-color: #d97706; } QPushButton:disabled { background-color: #d1d5db; }")
        btn_layout.addWidget(self.restart_btn)
        sidebar_layout.addLayout(btn_layout)

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
