"""Sidebar widget: complete sidebar UI component."""
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QWidget
)
from PyQt5.QtCore import pyqtSignal

from ui.widgets.collapsible import CollapsibleSection


class SidebarWidget(QFrame):
    """Complete sidebar with all controls and sections."""
    
    # Signals
    get_route_clicked = pyqtSignal()
    start_agent_clicked = pyqtSignal()
    restart_agent_clicked = pyqtSignal()
    quit_clicked = pyqtSignal()
    toggle_clicked = pyqtSignal()
    
    def __init__(self, config, parent=None):
        """Initialize sidebar."""
        super().__init__(parent)
        self.config = config
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup sidebar UI."""
        self.setStyleSheet(self.config.SIDEBAR_STYLE)
        self.setMaximumWidth(self.config.SIDEBAR_MAX_WIDTH)
        self.setMinimumWidth(self.config.SIDEBAR_MIN_WIDTH)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Top bar with close button
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        
        self.close_btn = QPushButton("☰")
        self.close_btn.setMaximumWidth(40)
        self.close_btn.setMaximumHeight(40)
        self.close_btn.setStyleSheet(self.config.BUTTON_STYLE_TOGGLE)
        self.close_btn.clicked.connect(self.toggle_clicked.emit)
        top_bar.addWidget(self.close_btn)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Title
        title = QLabel("Navigation")
        title.setStyleSheet(
            "font-weight: bold; font-size: 16px; color: #1f2937;"
        )
        layout.addWidget(title)

        # Coordinate inputs
        self._add_coord_inputs(layout)
        
        # K routes
        k_frame = QHBoxLayout()
        k_frame.addWidget(QLabel("K routes:"))
        self.k_entry = QLineEdit("1")
        self.k_entry.setStyleSheet(self.config.INPUT_STYLE)
        k_frame.addWidget(self.k_entry)
        layout.addLayout(k_frame)

        # Action buttons
        self._add_action_buttons(layout)

        # Map bounds
        self._add_bounds_display(layout)

        # Collapsible sections
        self._add_collapsible_sections(layout)

        layout.addStretch()

        # Quit button
        self.quit_btn = QPushButton("Quit (ESC)")
        self.quit_btn.clicked.connect(self.quit_clicked.emit)
        self.quit_btn.setStyleSheet(self.config.BUTTON_STYLE_DANGER)
        layout.addWidget(self.quit_btn)
    
    def _add_coord_inputs(self, layout) -> None:
        """Add coordinate input fields."""
        for label, attr, default in [
            ("Start Lat:", "start_lat", self.config.DEFAULT_START_LAT),
            ("Start Lon:", "start_lon", self.config.DEFAULT_START_LON),
            ("End Lat:", "end_lat", self.config.DEFAULT_END_LAT),
            ("End Lon:", "end_lon", self.config.DEFAULT_END_LON),
        ]:
            frame = QHBoxLayout()
            frame.addWidget(QLabel(label))
            line_edit = QLineEdit(str(default))
            line_edit.setStyleSheet(self.config.INPUT_STYLE)
            setattr(self, attr, line_edit)
            frame.addWidget(line_edit)
            layout.addLayout(frame)
    
    def _add_action_buttons(self, layout) -> None:
        """Add action buttons."""
        btn_layout = QVBoxLayout()

        self.get_route_btn = QPushButton("Get Route")
        self.get_route_btn.clicked.connect(self.get_route_clicked.emit)
        self.get_route_btn.setStyleSheet(self.config.BUTTON_STYLE_PRIMARY)
        btn_layout.addWidget(self.get_route_btn)

        self.start_agent_btn = QPushButton("Start Agent")
        self.start_agent_btn.clicked.connect(self.start_agent_clicked.emit)
        self.start_agent_btn.setEnabled(False)
        self.start_agent_btn.setStyleSheet(self.config.BUTTON_STYLE_SUCCESS)
        btn_layout.addWidget(self.start_agent_btn)

        self.restart_btn = QPushButton("Restart Agent")
        self.restart_btn.clicked.connect(self.restart_agent_clicked.emit)
        self.restart_btn.setEnabled(False)
        self.restart_btn.setStyleSheet(self.config.BUTTON_STYLE_WARNING)
        btn_layout.addWidget(self.restart_btn)

        layout.addLayout(btn_layout)
    
    def _add_bounds_display(self, layout) -> None:
        """Add map bounds display."""
        bounds_layout = QVBoxLayout()
        bounds_layout.addWidget(QLabel("Map bounds:"))
        self.bounds_label = QLabel("[-, -, -, -]")
        self.bounds_label.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: #6b7280;"
        )
        bounds_layout.addWidget(self.bounds_label)
        layout.addLayout(bounds_layout)
    
    def _add_collapsible_sections(self, layout) -> None:
        """Add collapsible sections."""
        # Route section
        self.route_text = QTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setStyleSheet(self.config.TEXT_AREA_STYLE)
        self.route_section = CollapsibleSection("Route")
        self.route_section.add_widget(self.route_text)
        layout.addWidget(self.route_section)

        # Status section
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet(self.config.TEXT_AREA_STYLE)
        self.status_section = CollapsibleSection("Agent Status")
        self.status_section.add_widget(self.status_text)
        layout.addWidget(self.status_section)

        # Speed section
        self.speed_label = QLabel("Speed: 0 km/h")
        self.speed_label.setStyleSheet(
            "font-weight: bold; color: #2563eb;"
        )
        self.speed_section = CollapsibleSection("Speed")
        self.speed_section.add_widget(self.speed_label)
        layout.addWidget(self.speed_section)

        # Points section (container for dynamic list)
        self.points_section = CollapsibleSection("Selected Points")
        self.points_container = QFrame()
        self.points_container.setStyleSheet(
            "QFrame { background-color: #f9fafb; border-radius: 6px; "
            "border: 1px solid #e5e7eb; }"
        )
        self.points_container.setMaximumHeight(200)
        points_layout = QVBoxLayout(self.points_container)
        points_layout.setContentsMargins(6, 6, 6, 6)
        points_layout.setSpacing(6)
        self.points_list_placeholder = QWidget()
        points_layout.addWidget(self.points_list_placeholder)
        points_layout.addStretch()
        self.points_section.add_widget(self.points_container)
        layout.addWidget(self.points_section)
