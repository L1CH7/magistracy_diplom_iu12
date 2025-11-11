"""UI setup for MainWindow - separated for clarity."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)
from PyQt5.QtCore import Qt

from src.client.ui.widgets.sidebar_widget import SidebarWidget


class MainWindowUI:
    """Mixin class with UI setup methods for MainWindow."""
    
    def _setup_sidebar(self) -> None:
        """Setup sidebar with header (close button + title)."""
        self.sidebar = SidebarWidget(self.map_frame)
        self.sidebar.setMaximumWidth(350)
        self.sidebar.setStyleSheet(
            "QFrame { background-color: rgba(255, 255, 255, 0.95); "
            "border: 1px solid #e5e7eb; border-radius: 12px; }"
        )
        
        # === SIDEBAR HEADER (close button + title) ===
        # Get common padding and calculate dimensions
        # P = 12px (sidebar padding), H1 = H2 = 32px (button/title height)
        # Layout: P + H1 + P + Navigation + P = 350px (sidebar width)
        sidebar_padding = 12
        header_height = 32
        
        # Create header container inside sidebar
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, sidebar_padding)
        header_layout.setSpacing(sidebar_padding)
        
        # Close button (× icon, inside sidebar, same height as Navigation)
        self.sidebar_close_btn = QPushButton("×")
        self.sidebar_close_btn.setFixedWidth(header_height)
        self.sidebar_close_btn.setFixedHeight(header_height)
        self.sidebar_close_btn.setStyleSheet(
            "QPushButton { background-color: #ef4444; color: white; "
            "border: none; border-radius: 6px; "
            "font-weight: bold; font-size: 20px; padding: 0px; } "
            "QPushButton:hover { background-color: #dc2626; }"
        )
        self.sidebar_close_btn.clicked.connect(self._toggle_sidebar)
        header_layout.addWidget(self.sidebar_close_btn)
        
        # Title label (takes remaining space, same height)
        self.title_label = QLabel("Navigation")
        self.title_label.setFixedHeight(header_height)
        self.title_label.setStyleSheet(
            "font-weight: bold; font-size: 16px; color: #1f2937; "
            "padding: 0px;"
        )
        header_layout.addWidget(self.title_label, 1)
        
        # Insert header at top of sidebar layout
        sidebar_layout = self.sidebar.layout()
        sidebar_layout.insertWidget(0, header_container)
        
        # === TOGGLE BUTTON (SEPARATE, always visible on map) ===
        # This button is OUTSIDE sidebar, positioned independently
        self.toggle_btn = QPushButton("☰", self.map_frame)
        self.toggle_btn.setFixedWidth(header_height)
        self.toggle_btn.setFixedHeight(header_height)
        self.toggle_btn.setStyleSheet(
            "QPushButton { background-color: rgba(59, 130, 246, 0.9); "
            "color: white; border: none; border-radius: 6px; "
            "font-weight: bold; font-size: 18px; padding: 0px; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        self.toggle_btn.clicked.connect(self._toggle_sidebar)
        self.toggle_btn.hide()  # Hidden when sidebar is visible
        
        # Connect sidebar buttons
        self.sidebar.get_route_btn.clicked.connect(self._on_get_route)
        self.sidebar.get_road_graph_btn.clicked.connect(self._on_get_road_graph)
        self.sidebar.quit_btn.clicked.connect(self.close)
        
        # Connect route panel signals
        self.sidebar.route_panel.get_routes_clicked.connect(
            self._on_get_k_routes
        )
        self.sidebar.route_panel.route_selected.connect(
            self._on_route_selected
        )
    
    def _setup_zoom_controls(self) -> None:
        """Setup zoom controls (slider + buttons)."""
        # Slider width = 12px, button width = 1.5 × 12 = 18px
        slider_width = 12
        button_width = int(slider_width * 1.5)
        
        zoom_container = QWidget(self.map_frame)
        zoom_container.setMaximumWidth(button_width + 10)
        zoom_layout = QVBoxLayout(zoom_container)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(4)
        zoom_layout.setAlignment(Qt.AlignCenter)
        
        # Zoom in button
        self.zoom_in_btn = QPushButton("+", zoom_container)
        self.zoom_in_btn.setFixedWidth(button_width)
        self.zoom_in_btn.setFixedHeight(24)
        self.zoom_in_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 255, 255, 0.9); "
            "border: 1px solid #d1d5db; border-radius: 6px; "
            "font-weight: bold; color: #374151; font-size: 16px; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 1); }"
        )
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        zoom_layout.addWidget(self.zoom_in_btn, 0, Qt.AlignCenter)
        
        # Zoom slider (vertical, height = 1/3 screen)
        self.zoom_slider = QSlider(Qt.Vertical, zoom_container)
        self.zoom_slider.setMinimum(0)
        self.zoom_slider.setMaximum(100)
        self.zoom_slider.setValue(50)
        self.zoom_slider.setFixedWidth(slider_width)
        self.zoom_slider.setStyleSheet(
            "QSlider { background-color: transparent; "
            "border: none; margin: 0px; padding: 0px; } "
            "QSlider::groove:vertical { border: none; "
            "background-color: rgba(255, 255, 255, 0.5); "
            f"border-radius: 4px; width: {slider_width}px; }} "
            "QSlider::handle:vertical { background: "
            "rgba(37, 99, 235, 0.9); border: none; border-radius: 6px; "
            "height: 16px; margin: 0px -4px; } "
            "QSlider::handle:vertical:hover { background: "
            "rgba(37, 99, 235, 1); }"
        )
        self.zoom_slider.sliderMoved.connect(self._on_zoom_slider_moved)
        self.zoom_slider.sliderPressed.connect(self._on_zoom_slider_pressed)
        self.zoom_slider.sliderReleased.connect(self._on_zoom_slider_released)
        self.zoom_slider.valueChanged.connect(
            self._on_zoom_slider_value_changed
        )
        self.zoom_slider.setPageStep(5)  # Jump by 5 when clicking track
        
        zoom_layout.addWidget(self.zoom_slider, 1, Qt.AlignCenter)
        
        # Zoom out button
        self.zoom_out_btn = QPushButton("−", zoom_container)
        self.zoom_out_btn.setFixedWidth(button_width)
        self.zoom_out_btn.setFixedHeight(24)
        self.zoom_out_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 255, 255, 0.9); "
            "border: 1px solid #d1d5db; border-radius: 6px; "
            "font-weight: bold; color: #374151; font-size: 16px; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 1); }"
        )
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        zoom_layout.addWidget(self.zoom_out_btn, 0, Qt.AlignCenter)
        
        self.zoom_container = zoom_container
        zoom_container.raise_()
