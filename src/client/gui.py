"""
Navigation MAS — Modern UI with sidebar, right-click picking, fullscreen map.
"""
import sys
import os
import threading
import time
import json
import requests
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs
from functools import partial

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QShortcut,
    QMainWindow, QFrame, QMenu, QSlider, QScrollArea,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, QTimer, Qt
from PyQt5.QtGui import QKeySequence, QCursor

# Handle both relative and absolute imports
try:
    from .models import Point, Route, NavigationState
    from .ui.widgets.collapsible import CollapsibleSection
    from .ui.widgets.web_console import WebConsolePage
    from .handlers import MapHandler
except ImportError:
    from models import Point, Route, NavigationState
    from ui.widgets.collapsible import CollapsibleSection
    from ui.widgets.web_console import WebConsolePage
    from handlers import MapHandler


class ZoomAPIHandler(SimpleHTTPRequestHandler):
    """HTTP handler for zoom API + assets serving."""

    gui_instance = None  # Will be set by NavigationGUI

    def do_GET(self):
        """Handle GET requests for both API and static files."""
        # Parse URL
        path = self.path.split('?')[0]
        query_string = self.path.split('?')[1] if '?' in self.path else ''

        # Handle API endpoints
        if path == '/api/zoom':
            # Parse zoom value from query string
            params = parse_qs(query_string)
            if 'value' in params:
                try:
                    zoom_value = float(params['value'][0])
                    # Update GUI zoom slider if instance is available
                    if self.gui_instance:
                        self.gui_instance._handle_zoom_from_js(
                            zoom_value
                        )
                    # Send 200 OK
                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'OK')
                    return
                except (ValueError, IndexError):
                    self.send_response(400)
                    self.end_headers()
                    return

        # Fall back to serving static files
        super().do_GET()


class NavigationGUI(QMainWindow):
    """Main window: fullscreen map + collapsible left sidebar."""

    def __init__(self, server_url: str = "http://server:8000"):
        super().__init__()
        self.server_url = server_url
        
        # Initialize navigation state - Single Source of Truth
        self.nav_state = NavigationState()
        
        # Initialize map handler
        self.map_handler = None  # Will be created in setup_ui
        
        self.agent_id = None
        self.map_ready = False
        self._graph_geojson = None
        self._routes_ml = None
        self._last_agent_pos = None
        self.prev_pos = None
        self.prev_time = None
        self._last_context_menu_pos = None
        self._context_menu_timer = None
        # Track points as array: first=from, last=to, middle=via
        # Each point: {"lon": float, "lat": float, "color": str}
        self.points = []
        self.points_list_widget = None
        # Color palette for via points (beautiful, non-acidic)
        self.color_palette = [
            "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
            "#ec4899", "#a855f7", "#0ea5e9", "#10b981"
        ]
        self._color_idx = 0
        # Map colors for display
        self.from_map_color = "#2563eb"  # Blue
        self.to_map_color = "#dc2626"    # Red
        # Zoom slider dragging state
        self._zoom_slider_user_dragging = False
        self._tile_url = os.environ.get(
            "TILE_URL",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        )

        self.setWindowTitle("Navigation MAS — Fullscreen Map")
        self.setGeometry(0, 0, 1400, 900)
        self.showMaximized()

        self.setup_ui()
        self.load_graph()

    def setup_ui(self) -> None:
        """Create main layout: sidebar (left, collapsible) + map (right, main)."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== LEFT SIDEBAR (collapsible) =====
        self.sidebar = QFrame()
        self.sidebar.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; "
            "border-radius: 8px; }"
        )
        self.sidebar.setMaximumWidth(350)
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMinimumHeight(600)  # Full height
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

        # === Top bar with close/open button ===
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        
        # Close button (shown when sidebar is open) - same style as open btn
        self.sidebar_close_btn = QPushButton("☰")
        self.sidebar_close_btn.setMaximumWidth(40)
        self.sidebar_close_btn.setMaximumHeight(40)
        self.sidebar_close_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            "border: none; border-radius: 4px; font-weight: bold; "
            "font-size: 18px; } "
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.sidebar_close_btn.clicked.connect(self._toggle_sidebar)
        top_bar_layout.addWidget(self.sidebar_close_btn)
        
        top_bar_layout.addStretch()
        sidebar_layout.addLayout(top_bar_layout)

        # === Open button (overlay, shown when sidebar is hidden) ===
        self.sidebar_open_btn = QPushButton("☰")
        self.sidebar_open_btn.setMaximumWidth(40)
        self.sidebar_open_btn.setMaximumHeight(40)
        self.sidebar_open_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            "border: none; border-radius: 4px; font-weight: bold; "
            "font-size: 18px; } "
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.sidebar_open_btn.clicked.connect(self._toggle_sidebar)
        self.sidebar_visible = True

        # Title
        title_label = QLabel("Navigation")
        title_label.setStyleSheet(
            "font-weight: bold; font-size: 16px; color: #1f2937;"
        )
        sidebar_layout.addWidget(title_label)

        # Start/End coords
        start_frame = QHBoxLayout()
        start_frame.addWidget(QLabel("Start Lat:"))
        self.start_lat = QLineEdit("55.751244")
        self.start_lat.setStyleSheet(
            "QLineEdit { border-radius: 4px; padding: 4px; "
            "border: 1px solid #d1d5db; }"
        )
        start_frame.addWidget(self.start_lat)
        sidebar_layout.addLayout(start_frame)

        start_frame2 = QHBoxLayout()
        start_frame2.addWidget(QLabel("Start Lon:"))
        self.start_lon = QLineEdit("37.618423")
        self.start_lon.setStyleSheet(
            "QLineEdit { border-radius: 4px; padding: 4px; "
            "border: 1px solid #d1d5db; }"
        )
        start_frame2.addWidget(self.start_lon)
        sidebar_layout.addLayout(start_frame2)

        end_frame = QHBoxLayout()
        end_frame.addWidget(QLabel("End Lat:"))
        self.end_lat = QLineEdit("55.755826")
        self.end_lat.setStyleSheet(
            "QLineEdit { border-radius: 4px; padding: 4px; "
            "border: 1px solid #d1d5db; }"
        )
        end_frame.addWidget(self.end_lat)
        sidebar_layout.addLayout(end_frame)

        end_frame2 = QHBoxLayout()
        end_frame2.addWidget(QLabel("End Lon:"))
        self.end_lon = QLineEdit("37.617300")
        self.end_lon.setStyleSheet(
            "QLineEdit { border-radius: 4px; padding: 4px; "
            "border: 1px solid #d1d5db; }"
        )
        end_frame2.addWidget(self.end_lon)
        sidebar_layout.addLayout(end_frame2)

        # K routes
        k_frame = QHBoxLayout()
        k_frame.addWidget(QLabel("K routes:"))
        self.k_entry = QLineEdit("1")
        self.k_entry.setStyleSheet(
            "QLineEdit { border-radius: 4px; padding: 4px; "
            "border: 1px solid #d1d5db; }"
        )
        k_frame.addWidget(self.k_entry)
        sidebar_layout.addLayout(k_frame)

        # Buttons
        btn_layout = QVBoxLayout()

        self.get_route_btn = QPushButton("Get Route")
        self.get_route_btn.clicked.connect(self.get_route)
        self.get_route_btn.setStyleSheet(
            "QPushButton { background-color: #3b82f6; color: white; "
            "border: none; border-radius: 6px; padding: 8px; font-weight: bold; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        btn_layout.addWidget(self.get_route_btn)

        self.start_agent_btn = QPushButton("Start Agent")
        self.start_agent_btn.clicked.connect(self.start_agent)
        self.start_agent_btn.setEnabled(False)
        self.start_agent_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "border: none; border-radius: 6px; padding: 8px; font-weight: bold; } "
            "QPushButton:hover { background-color: #059669; } "
            "QPushButton:disabled { background-color: #d1d5db; }"
        )
        btn_layout.addWidget(self.start_agent_btn)

        self.restart_btn = QPushButton("Restart Agent")
        self.restart_btn.clicked.connect(self.restart_agent)
        self.restart_btn.setEnabled(False)
        self.restart_btn.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: white; "
            "border: none; border-radius: 6px; padding: 8px; font-weight: bold; } "
            "QPushButton:hover { background-color: #d97706; } "
            "QPushButton:disabled { background-color: #d1d5db; }"
        )
        btn_layout.addWidget(self.restart_btn)

        sidebar_layout.addLayout(btn_layout)

        # Map bounds
        bounds_layout = QVBoxLayout()
        bounds_layout.addWidget(
            QLabel("Map bounds:") if True else None
        )
        self.bounds_label = QLabel("[-, -, -, -]")
        self.bounds_label.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: #6b7280;"
        )
        bounds_layout.addWidget(self.bounds_label)
        sidebar_layout.addLayout(bounds_layout)

        # Collapsible logs
        self.route_text = QTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setStyleSheet(
            "QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; "
            "background-color: #f9fafb; font-size: 10px; }"
        )
        self.route_section = CollapsibleSection("Route")
        self.route_section.add_widget(self.route_text)
        sidebar_layout.addWidget(self.route_section)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet(
            "QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; "
            "background-color: #f9fafb; font-size: 10px; }"
        )
        self.status_section = CollapsibleSection("Agent Status")
        self.status_section.add_widget(self.status_text)
        sidebar_layout.addWidget(self.status_section)

        self.speed_label = QLabel("Speed: 0 km/h")
        self.speed_label.setStyleSheet("font-weight: bold; color: #2563eb;")
        self.speed_section = CollapsibleSection("Speed")
        self.speed_section.add_widget(self.speed_label)
        sidebar_layout.addWidget(self.speed_section)

        # === SELECTED POINTS LIST ===
        self.points_section = CollapsibleSection("Selected Points")
        self.points_container = QFrame()
        self.points_container.setStyleSheet(
            "QFrame { background-color: #f9fafb; border-radius: 6px; "
            "border: 1px solid #e5e7eb; }"
        )
        self.points_container.setMaximumHeight(200)
        points_container_layout = QVBoxLayout(self.points_container)
        points_container_layout.setContentsMargins(6, 6, 6, 6)
        points_container_layout.setSpacing(6)
        self.points_list = QWidget()  # Placeholder
        points_container_layout.addWidget(self.points_list)
        points_container_layout.addStretch()
        self.points_section.add_widget(self.points_container)
        sidebar_layout.addWidget(self.points_section)

        sidebar_layout.addStretch()

        # Quit button
        self.quit_btn = QPushButton("Quit (ESC)")
        self.quit_btn.clicked.connect(self.close)
        self.quit_btn.setStyleSheet(
            "QPushButton { background-color: #ef4444; color: white; "
            "border: none; border-radius: 6px; padding: 8px; font-weight: bold; } "
            "QPushButton:hover { background-color: #dc2626; }"
        )
        sidebar_layout.addWidget(self.quit_btn)

        # ===== MAP AREA WITH OVERLAY CONTROLS =====
        # Create map frame (will contain map + overlay controls)
        self.map_frame = QFrame()
        self.map_frame.setStyleSheet(
            "QFrame { background-color: #f3f4f6; }"
        )
        map_layout = QVBoxLayout(self.map_frame)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(0)

        # Web view (map)
        self.web_view = QWebEngineView()
        map_layout.addWidget(self.web_view, 1)

        # === SIDEBAR AS OVERLAY (can be hidden/shown) ===
        self.sidebar.setParent(self.map_frame)
        self.sidebar.setMaximumWidth(350)
        
        # === TOP-LEFT: Sidebar open button (overlay, shown when sidebar is hidden) ===
        # Created during sidebar_open_btn initialization, no need to set parent here
        
        # === RIGHT-CENTER: Zoom controls (overlay, semi-transparent) ===
        zoom_container = QWidget()
        zoom_container.setParent(self.map_frame)
        zoom_container.setMaximumWidth(60)
        zoom_layout = QVBoxLayout(zoom_container)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(2)
        
        # zoom in/out button 
        zoom_button_size = 15
        # Zoom in button
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setMinimumWidth(zoom_button_size)
        self.zoom_in_btn.setMaximumWidth(zoom_button_size)
        self.zoom_in_btn.setMinimumHeight(zoom_button_size)
        self.zoom_in_btn.setMaximumHeight(zoom_button_size)
        self.zoom_in_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 255, 255, 0.8); "
            "border: 1px solid #d1d5db; border-radius: 4px; "
            "font-weight: bold; color: #374151; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 1); }"
        )
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        zoom_layout.addWidget(self.zoom_in_btn)
        
        # Zoom slider
        self.zoom_slider = QSlider(Qt.Vertical)
        self.zoom_slider.setMinimum(0)
        self.zoom_slider.setMaximum(100)
        self.zoom_slider.setValue(50)  # Start at center
        self.zoom_slider.setStyleSheet(
            "QSlider { background-color: transparent; "
            "border: none; margin: 0px; padding: 0px; } "
            "QSlider::groove:vertical { border: none; "
            "background-color: rgba(255, 255, 255, 0.5); "
            "border-radius: 4px; width: 8px; } "
            "QSlider::handle:vertical { background: "
            "rgba(37, 99, 235, 0.9); border: none; border-radius: 6px; "
            "height: 16px; margin: 0px -4px; } "
            "QSlider::handle:vertical:hover { background: "
            "rgba(37, 99, 235, 1); }"
        )
        self.zoom_slider.sliderMoved.connect(
            self._on_zoom_slider_moved
        )
        self.zoom_slider.sliderPressed.connect(
            self._on_zoom_slider_pressed
        )
        self.zoom_slider.sliderReleased.connect(
            self._on_zoom_slider_released
        )
        zoom_layout.addWidget(self.zoom_slider, 1)
        
        # Zoom out button
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setMinimumWidth(zoom_button_size)
        self.zoom_out_btn.setMaximumWidth(zoom_button_size)
        self.zoom_out_btn.setMinimumHeight(zoom_button_size)
        self.zoom_out_btn.setMaximumHeight(zoom_button_size)
        self.zoom_out_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255, 255, 255, 0.8); "
            "border: 1px solid #d1d5db; border-radius: 4px; "
            "font-weight: bold; color: #374151; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 1); }"
        )
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        zoom_layout.addWidget(self.zoom_out_btn)
        
        zoom_container.raise_()
        
        # === BOTTOM-LEFT: Scale ruler (overlay) ===
        self.scale_ruler = QLabel("50m")
        self.scale_ruler.setParent(self.map_frame)
        self.scale_ruler.setVisible(False)  # Hidden
        
        self.scale_ruler_line = QFrame()
        self.scale_ruler_line.setParent(self.map_frame)
        self.scale_ruler_line.setVisible(False)  # Hidden
        
        # Track zoom bounds for slider
        self.current_zoom = 12.0  # Will be updated on map load
        self.initial_zoom = 12.0  # Will be updated on map load
        self.zoom_min = 0.2 * 12.0  # Will be updated on map load
        self.zoom_max = 5.0 * 12.0  # Will be updated on map load

        main_layout.addWidget(self.map_frame, stretch=1)

        # ===== Initialize Map Handler =====
        self.map_handler = MapHandler(self, self.nav_state)
        
        # ===== Load map =====
        self._assets_port = self.map_handler.start_assets_server()
        map_url = QUrl(f"http://127.0.0.1:{self._assets_port}/map.html")
        self.web_view.setPage(WebConsolePage(self.web_view))
        self.web_view.load(map_url)
        self.web_view.loadFinished.connect(self._on_map_html_loaded)
        self.web_view.loadFinished.connect(self.on_map_loaded)

        # ESC to quit
        QShortcut(QKeySequence("Esc"), self, activated=self._on_quit)
        
        # Ctrl+1/2/3 for quick point setting at cursor
        QShortcut(QKeySequence("Ctrl+1"), self, activated=self._on_ctrl_1)
        QShortcut(QKeySequence("Ctrl+2"), self, activated=self._on_ctrl_2)
        QShortcut(QKeySequence("Ctrl+3"), self, activated=self._on_ctrl_3)
        
        # Setup zoom change callback - this will be called by map.html
        # when zoom changes (any method: wheel, buttons, slider, etc)
        self._setup_zoom_callback()

    def _start_assets_httpd(self) -> int:
        """Start HTTP server for map.html assets + zoom API."""
        assets_dir = "/app/src/client/assets"
        handler = partial(ZoomAPIHandler, directory=assets_dir)
        # Store reference to this GUI instance in handler
        ZoomAPIHandler.gui_instance = self
        httpd = ThreadingHTTPServer(("127.0.0.1", 9999), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return port

    def _handle_zoom_from_js(self, zoom_value: float) -> None:
        """Handle zoom change from JavaScript via HTTP API.
        
        TODO: This should be moved to MapHandler and use nav_state.zoom_changed
        signal instead. The slider update should happen via signal connection.
        """
        try:
            self.current_zoom = zoom_value

            # Convert zoom level back to slider position (0-100)
            zoom_min = 0
            zoom_max = 19
            # Reverse exponential: slider_pos = (zoom_level / span) ^ (1/1.3)
            normalized = (zoom_value - zoom_min) / (zoom_max - zoom_min)
            slider_pos = int(round((normalized ** (1.0 / 1.3)) * 100))
            slider_pos = max(0, min(100, slider_pos))

            # Update slider without triggering valueChanged signal
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(slider_pos)
            self.zoom_slider.blockSignals(False)
            
            # TODO: Emit zoom_changed signal here
            # self.nav_state.set_zoom(zoom_value)
        except Exception as e:
            print(f"Error handling zoom from JS: {e}")

    def _on_map_html_loaded(self, ok: bool) -> None:
        """Inject TILE_URL after map.html loads."""
        if not ok:
            print("ERROR: map.html failed to load")
            return
        if self.map_handler:
            self.map_handler.on_map_html_loaded()
        else:
            # Fallback
            code = f"window.TILE_URL = {json.dumps(self._tile_url)};"
            print(f"DEBUG: Injecting TILE_URL: {self._tile_url}")
            self.web_view.page().runJavaScript(code)

    def _setup_map_context_menu(self) -> None:
        """Install JS callback for right-click context menu.
        
        TODO: This method and related polling should be moved to MapHandler.
        The context menu setup is already partially in MapHandler.setup_map_context_menu()
        but GUI still has these duplicate methods. Consolidate them.
        """
        # Install JS callbacks
        js_code = """
        window.lastContextMenuPos = null;
        window.lastContextMenuProcessed = false;
        
        window.onMapContextMenu = function(pos) {
            console.log('RightClick at:', pos.lon, pos.lat);
            // Store last position for Python to retrieve
            window.lastContextMenuPos = pos;
            window.lastContextMenuProcessed = false;
        };
        """
        self.web_view.page().runJavaScript(js_code)
        
        # Start polling timer to check for right-click events
        self._context_menu_timer = QTimer()
        self._context_menu_timer.timeout.connect(self._poll_context_menu_pos)
        self._context_menu_timer.start(20)  # Poll every 20ms for faster response
    
    def _poll_context_menu_pos(self) -> None:
        """Poll for right-click position from JavaScript."""
        self.web_view.page().runJavaScript(
            "JSON.stringify(window.lastContextMenuPos)",
            lambda result: self._on_context_menu_pos_received(result)
        )

    def _show_map_context_menu(self, lon: float, lat: float) -> None:
        """Show simple context menu for map right-click."""
        menu = QMenu(self)
        menu.setWindowOpacity(0.95)
        menu.setMinimumWidth(180)
        
        # Main actions only
        action_from = menu.addAction("Set From Point")
        action_to = menu.addAction("Set To Point")
        
        # Via is only available if we have at least 2 points
        action_via = None
        if len(self.points) >= 2:
            action_via = menu.addAction("Add Via Point")
        
        menu.addSeparator()
        action_clear = menu.addAction("Clear All")
        
        # Connect actions
        action_from.triggered.connect(
            lambda: self._set_point("from", lon, lat)
        )
        action_to.triggered.connect(
            lambda: self._set_point("to", lon, lat)
        )
        if action_via:
            action_via.triggered.connect(
                lambda: self._set_point("via", lon, lat)
            )
        action_clear.triggered.connect(self._clear_map_markers)
        
        menu.exec_(QCursor.pos())

    def _on_context_menu_pos_received(self, result: str) -> None:
        """Handle right-click position received from JavaScript."""
        if not result or result == "null":
            return
        
        try:
            import json
            pos = json.loads(result)
            if pos and isinstance(pos, dict):
                lon = pos.get("lon")
                lat = pos.get("lat")
                if lon is not None and lat is not None:
                    # Round to avoid floating point comparison issues
                    lon_r = round(lon, 4)
                    lat_r = round(lat, 4)
                    last_pos_r = (
                        round(self._last_context_menu_pos[0], 4),
                        round(self._last_context_menu_pos[1], 4)
                    ) if self._last_context_menu_pos else None
                    
                    # Show menu if this is a genuinely new position
                    if last_pos_r != (lon_r, lat_r):
                        self._last_context_menu_pos = (lon, lat)
                        # Minimal delay
                        QTimer.singleShot(
                            10,
                            lambda: self._show_map_context_menu(lon, lat)
                        )
                        # Clear the position immediately
                        self.web_view.page().runJavaScript(
                            "window.lastContextMenuPos = null;"
                        )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    def _set_point(self, point_type: str, lon: float, lat: float) -> None:
        """Set a point on map via context menu."""
        if point_type == "from":
            # Set first point - always replaces existing from
            color = self.color_palette[
                self._color_idx % len(self.color_palette)
            ]
            self._color_idx += 1
            
            if not self.points:
                self.points.append({
                    "lon": lon, "lat": lat, "color": color
                })
            else:
                self.points[0] = {
                    "lon": lon, "lat": lat, "color": color
                }
            self.start_lat.setText(f"{lat:.6f}")
            self.start_lon.setText(f"{lon:.6f}")
        
        elif point_type == "to":
            # Set last point - always replaces existing to
            color = self.color_palette[
                self._color_idx % len(self.color_palette)
            ]
            self._color_idx += 1
            
            if len(self.points) == 0:
                self.points.append({
                    "lon": lon, "lat": lat, "color": color
                })
            elif len(self.points) == 1:
                self.points.append({
                    "lon": lon, "lat": lat, "color": color
                })
            else:
                # Replace last
                self.points[-1] = {
                    "lon": lon, "lat": lat, "color": color
                }
            
            self.end_lat.setText(f"{lat:.6f}")
            self.end_lon.setText(f"{lon:.6f}")
        
        elif point_type == "via":
            # Via point - gets random color from palette
            # Insert before last (to) point
            if len(self.points) < 2:
                # Not enough points for via yet
                return
            
            color = self.color_palette[
                self._color_idx % len(self.color_palette)
            ]
            self._color_idx += 1
            
            # Insert before the last point (which is "to")
            self.points.insert(-1, {
                "lon": lon, "lat": lat, "color": color
            })
        
        # Update map markers and list
        self._update_map_markers()
        self._update_points_list()

    def _update_map_markers(self) -> None:
        """Clear all markers and add only current points from array."""
        # Clear ALL old markers first
        self._js("window.app && window.app.clearAllMarkers();")
        
        if not self.points:
            return
        
        # Add markers for each point with correct color
        for idx, point in enumerate(self.points):
            lon = point["lon"]
            lat = point["lat"]
            
            if idx == 0:
                # From - blue border (white fill)
                marker_color = "#2563eb"
            elif idx == len(self.points) - 1:
                # To - red border (white fill)
                marker_color = "#dc2626"
            else:
                # Via - its own color with black border
                marker_color = point["color"]
            
            # Add marker to map
            code = (
                f"window.app && "
                f"window.app.addMarker({{"
                f"lon: {lon}, lat: {lat}"
                f"}}, '{marker_color}');"
            )
            self._js(code)

    def _remove_point(self, idx: int) -> None:
        """Remove a point at specific index from the points array."""
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            
            # Update from/to fields if needed
            if len(self.points) == 0:
                self.start_lat.setText("55.751244")
                self.start_lon.setText("37.618423")
                self.end_lat.setText("55.755826")
                self.end_lon.setText("37.617300")
            elif len(self.points) == 1:
                p = self.points[0]
                self.start_lat.setText(f"{p['lat']:.6f}")
                self.start_lon.setText(f"{p['lon']:.6f}")
                self.end_lat.setText("55.755826")
                self.end_lon.setText("37.617300")
            else:
                p0 = self.points[0]
                p1 = self.points[-1]
                self.start_lat.setText(f"{p0['lat']:.6f}")
                self.start_lon.setText(f"{p0['lon']:.6f}")
                self.end_lat.setText(f"{p1['lat']:.6f}")
                self.end_lon.setText(f"{p1['lon']:.6f}")
            
            # Update markers (only the remaining ones)
            self._update_map_markers()
        
        self._update_points_list()

    def _clear_map_markers(self) -> None:
        """Clear all map markers and points."""
        self.points = []
        self.start_lat.setText("55.751244")
        self.start_lon.setText("37.618423")
        self.end_lat.setText("55.755826")
        self.end_lon.setText("37.617300")
        self._js("window.app && window.app.clearAllMarkers();")
        self._update_points_list()

    def _update_points_list(self) -> None:
        """Update the points list display as scrollable sandwich."""
        # Remove old list widget
        if hasattr(self, 'points_list_widget') and self.points_list_widget:
            self.points_list_widget.deleteLater()
        
        # Create new container
        self.points_list_widget = QWidget()
        layout = QVBoxLayout(self.points_list_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        if not self.points:
            # No points - hide the entire list widget
            layout.addStretch()
        else:
            # Create scroll area for sandwich
            scroll_area = QScrollArea()
            scroll_area.setStyleSheet(
                "QScrollArea { border: none; background-color: #ffffff; } "
                "QScrollBar:vertical { width: 6px; } "
                "QScrollBar::handle:vertical { background: #d1d5db; "
                "border-radius: 3px; } "
                "QScrollBar::handle:vertical:hover { background: #9ca3af; }"
            )
            scroll_area.setWidgetResizable(True)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            
            # Create sandwich container
            sandwich = self._create_sandwich()
            scroll_area.setWidget(sandwich)
            
            # Set max height to show ~5 points
            point_height = 36
            max_points_visible = 5
            max_height = min(
                len(self.points) * point_height,
                max_points_visible * point_height
            )
            scroll_area.setMaximumHeight(max_height)
            scroll_area.setMinimumHeight(
                min(len(self.points) * point_height, max_height)
            )
            
            layout.addWidget(scroll_area)
        
        # Add to container
        old_widget = self.points_container.layout().takeAt(0)
        if old_widget and old_widget.widget():
            old_widget.widget().deleteLater()
        self.points_container.layout().insertWidget(
            0, self.points_list_widget
        )

    def _create_sandwich(self) -> QFrame:
        """Create a sandwich-style list of points with tight tiles."""
        container = QFrame()
        container.setStyleSheet(
            "QFrame { background-color: #ffffff; "
            "border: 1px solid #d1d5db; border-radius: 6px; "
            "margin: 0px; padding: 0px; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        n = len(self.points)
        for idx in range(n):
            point = self.points[idx]
            is_first = (idx == 0)
            is_last = (idx == n - 1)
            
            tile = self._create_sandwich_tile(idx, point, is_first, is_last)
            layout.addWidget(tile)
        
        return container

    def _create_sandwich_tile(
        self, idx: int, point: dict, is_first: bool, is_last: bool
    ) -> QFrame:
        """Create a tile for one point in the sandwich."""
        tile = QFrame()
        
        # Styling - only bottom border between tiles
        tile.setStyleSheet(
            "QFrame { background-color: #ffffff; "
            "border: none; border-bottom: 1px solid #e5e7eb; "
            "padding: 0px; margin: 0px; }"
        )
        tile.setMaximumHeight(32)
        tile.setMinimumHeight(32)
        
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        
        # 1. Marker circle matching map display
        dot = QFrame()
        
        if is_first:
            # From: white circle with blue border
            dot.setMinimumWidth(14)
            dot.setMaximumWidth(14)
            dot.setMinimumHeight(14)
            dot.setMaximumHeight(14)
            dot.setStyleSheet(
                "QFrame { background-color: #ffffff; "
                "border: 2px solid #2563eb; border-radius: 7px; }"
            )
        elif is_last:
            # To: white circle with red border
            dot.setMinimumWidth(14)
            dot.setMaximumWidth(14)
            dot.setMinimumHeight(14)
            dot.setMaximumHeight(14)
            dot.setStyleSheet(
                "QFrame { background-color: #ffffff; "
                "border: 2px solid #dc2626; border-radius: 7px; }"
            )
        else:
            # Via: colored circle with black border
            color = point.get("color", "#8b5cf6")
            dot.setMinimumWidth(12)
            dot.setMaximumWidth(12)
            dot.setMinimumHeight(12)
            dot.setMaximumHeight(12)
            dot.setStyleSheet(
                f"QFrame {{ background-color: {color}; "
                f"border: 2px solid #000000; border-radius: 6px; }}"
            )
        
        layout.addWidget(dot)
        
        # 2. Point type label
        if is_first:
            type_label = QLabel("From")
        elif is_last:
            type_label = QLabel("To")
        else:
            type_label = QLabel("Via")
        
        type_label.setStyleSheet(
            "font-size: 11px; color: #374151; min-width: 24px;"
        )
        layout.addWidget(type_label)
        
        # 3. Coordinates (compact)
        coord_text = f"{point['lon']:.2f}, {point['lat']:.2f}"
        coord_label = QLabel(coord_text)
        coord_label.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: #6b7280;"
        )
        layout.addWidget(coord_label, 1)
        
        # 4. Up button (not for first)
        if idx > 0:
            up_btn = QPushButton("▲")
            up_btn.setMinimumWidth(20)
            up_btn.setMaximumWidth(20)
            up_btn.setMinimumHeight(20)
            up_btn.setMaximumHeight(20)
            up_btn.setStyleSheet(
                "QPushButton { background-color: transparent; "
                "border: none; padding: 0px; "
                "color: #9ca3af; font-size: 9px; font-weight: bold; } "
                "QPushButton:hover { color: #6b7280; }"
            )
            up_btn.clicked.connect(lambda: self._move_point(idx, -1))
            layout.addWidget(up_btn)
        
        # 5. Down button (not for last)
        if idx < len(self.points) - 1:
            down_btn = QPushButton("▼")
            down_btn.setMinimumWidth(20)
            down_btn.setMaximumWidth(20)
            down_btn.setMinimumHeight(20)
            down_btn.setMaximumHeight(20)
            down_btn.setStyleSheet(
                "QPushButton { background-color: transparent; "
                "border: none; padding: 0px; "
                "color: #9ca3af; font-size: 9px; font-weight: bold; } "
                "QPushButton:hover { color: #6b7280; }"
            )
            down_btn.clicked.connect(lambda: self._move_point(idx, 1))
            layout.addWidget(down_btn)
        
        # 6. Delete button
        del_btn = QPushButton("✕")
        del_btn.setMinimumWidth(20)
        del_btn.setMaximumWidth(20)
        del_btn.setMinimumHeight(20)
        del_btn.setMaximumHeight(20)
        del_btn.setStyleSheet(
            "QPushButton { background-color: transparent; "
            "border: none; padding: 0px; "
            "color: #ef4444; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { color: #dc2626; }"
        )
        del_btn.clicked.connect(lambda: self._remove_point(idx))
        layout.addWidget(del_btn)
        
        return tile

    def _move_point(self, from_idx: int, direction: int) -> None:
        """Move a point up (-1) or down (+1) in the list."""
        to_idx = from_idx + direction
        if 0 <= to_idx < len(self.points):
            self.points[from_idx], self.points[to_idx] = (
                self.points[to_idx], self.points[from_idx]
            )
        
        # Update both map and list display
        self._update_map_markers()
        self._update_points_list()

    def _js(self, code: str) -> None:
        """Execute JS on map."""
        if self.map_ready:
            self.web_view.page().runJavaScript(code)

    def load_graph(self) -> None:
        """Load graph from server in background."""

        def worker():
            graph_nodes = {}
            graph_edges = []
            try:
                resp = requests.get(
                    f"{self.server_url}/graph", timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    graph_nodes.update(
                        {n["id"]: n for n in data["nodes"]}
                    )
                    graph_edges = data["edges"]
            except Exception as e:
                print(f"Failed to load graph: {e}")
                return

            features = []
            for edge in graph_edges[:5000]:
                u, v = edge["u"], edge["v"]
                if u in graph_nodes and v in graph_nodes:
                    u_data, v_data = (
                        graph_nodes[u],
                        graph_nodes[v],
                    )
                    features.append({
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [u_data["lon"], u_data["lat"]],
                                [v_data["lon"], v_data["lat"]],
                            ],
                        },
                    })

            graph_geojson = {
                "type": "FeatureCollection",
                "features": features,
            }

            def apply():
                self._graph_geojson = graph_geojson
                code = (
                    "window.app && window.app.setGraphGeoJSON("
                    f"{json.dumps(graph_geojson)}"
                    ");"
                )
                self._js(code)
                self._js("window.app && window.app.fitToGraph();")

            QTimer.singleShot(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def get_route(self) -> None:
        """Fetch route from server."""
        try:
            start_lat = float(self.start_lat.text())
            start_lon = float(self.start_lon.text())
            end_lat = float(self.end_lat.text())
            end_lon = float(self.end_lon.text())
        except ValueError:
            self.status_text.append("Invalid coordinates")
            return

        k_val = (
            int(self.k_entry.text())
            if self.k_entry.text().isdigit()
            else 1
        )
        req = {
            "start": {"lat": start_lat, "lon": start_lon},
            "end": {"lat": end_lat, "lon": end_lon},
            "k": k_val,
        }
        self.get_route_btn.setEnabled(False)

        def worker():
            try:
                resp = requests.post(
                    f"{self.server_url}/route",
                    json=req,
                    timeout=20,
                )
                ok = resp.status_code == 200
                data = resp.json() if ok else {"error": resp.text}
            except Exception as e:
                ok = False
                data = {"error": str(e)}

            def apply():
                if not ok:
                    self.status_text.append(
                        f"Failed to get route: {data['error']}"
                    )
                else:
                    self.routes = data["routes"]
                    self.current_route_index = 0
                    self.route_text.clear()
                    for i, r in enumerate(self.routes):
                        self.route_text.append(
                            f"Route {i+1}: "
                            f"{len(r['nodes'])} nodes, "
                            f"{r['total_distance']:.2f}m, "
                            f"{r['estimated_time']:.2f}s"
                        )
                    self.start_agent_btn.setEnabled(True)
                    colors = [
                        "#2563eb",
                        "#ef4444",
                        "#10b981",
                        "#f59e0b",
                        "#8b5cf6",
                    ]
                    ml_routes = []
                    for i, r in enumerate(self.routes):
                        coords = [
                            [p["lon"], p["lat"]]
                            for p in r["positions"]
                        ]
                        ml_routes.append({
                            "id": f"route{i+1}",
                            "coords": coords,
                            "color": colors[i % len(colors)],
                        })
                    self._routes_ml = ml_routes
                    code = (
                        "window.app && "
                        "window.app.setRoutes("
                        f"{json.dumps(ml_routes)}"
                        ");"
                    )
                    self._js(code)
                    self._js(
                        "window.app && "
                        "window.app.fitToRoutes();"
                    )
                self.get_route_btn.setEnabled(True)

            QTimer.singleShot(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def start_agent(self) -> None:
        """Start agent simulation."""
        if not hasattr(self, "routes") or not self.routes:
            self.status_text.append("Get routes first")
            return

        try:
            req = {
                "route_nodes": (
                    self.routes[self.current_route_index]["nodes"]
                ),
                "params": {
                    "max_speed": 50.0,
                    "power": 100.0,
                    "length": 5.0,
                    "width": 2.0,
                },
            }
            resp = requests.post(
                f"{self.server_url}/agent/start",
                json=req,
                timeout=10,
            )
            if resp.status_code == 200:
                state = resp.json()
                self.agent_id = state["agent_id"]
                self.status_text.clear()
                self.status_text.append(
                    f"Agent {self.agent_id} started at "
                    f"node {state['index']}"
                )
                self.restart_btn.setEnabled(True)
                threading.Thread(
                    target=self.simulate_agent, daemon=True
                ).start()
            else:
                self.status_text.append(
                    f"Failed to start agent: {resp.text}"
                )
        except Exception as e:
            self.status_text.append(str(e))

    def simulate_agent(self) -> None:
        """Agent simulation loop."""
        while self.agent_id:
            try:
                resp = requests.post(
                    f"{self.server_url}/agent/{self.agent_id}/step",
                    timeout=10,
                )
                if resp.status_code == 200:
                    state = resp.json()
                    current_time = time.time()
                    if self.prev_pos and self.prev_time:
                        lat_diff = (
                            state["position"]["lat"]
                            - self.prev_pos["lat"]
                        )
                        lon_diff = (
                            state["position"]["lon"]
                            - self.prev_pos["lon"]
                        )
                        dist = (
                            ((lat_diff**2 + lon_diff**2) ** 0.5)
                            * 111320
                        )
                        dt = current_time - self.prev_time
                        if dt > 0:
                            speed = min(dist / dt * 3.6, 120.0)
                            self.speed_label.setText(
                                f"Speed: {speed:.2f} km/h"
                            )
                    self.prev_pos = state["position"]
                    self.prev_time = current_time
                    self.status_text.clear()
                    self.status_text.append(
                        f"Agent {state['agent_id']} "
                        f"at index {state['index']}, "
                        f"pos: {state['position']}, "
                        f"done: {state['done']}"
                    )
                    pos = state["position"]
                    self._last_agent_pos = pos
                    agent_obj = json.dumps(
                        {"lat": pos["lat"], "lon": pos["lon"]}
                    )
                    code = (
                        "window.app && "
                        "window.app.updateAgent(" + agent_obj + ");"
                    )
                    self._js(code)
                    if state["done"]:
                        break
                else:
                    self.status_text.append(
                        f"Step failed: {resp.text}"
                    )
                    break
            except Exception as e:
                self.status_text.append(f"Error: {str(e)}")
                break
            time.sleep(0.1)

    def _update_bounds_label(self) -> None:
        """Update map bounds display."""
        if not self.map_ready:
            return

        def _apply_bounds(result):
            if not result or not isinstance(result, dict):
                return
            try:
                bbox = [
                    float(result.get("west")),
                    float(result.get("south")),
                    float(result.get("east")),
                    float(result.get("north")),
                ]
                fmt = (
                    f"[{bbox[0]:.5f}, {bbox[1]:.5f}, "
                    f"{bbox[2]:.5f}, {bbox[3]:.5f}]"
                )
                self.bounds_label.setText(fmt)
            except Exception:
                pass

        js = (
            "(function(){ if(!window.map) return null; "
            "const b=window.map.getBounds(); "
            "return {west:b.getWest(), south:b.getSouth(), "
            "east:b.getEast(), north:b.getNorth()}; })();"
        )
        self.web_view.page().runJavaScript(js, _apply_bounds)

    def _toggle_sidebar(self) -> None:
        """Toggle sidebar visibility without redrawing map."""
        self.sidebar_visible = not self.sidebar_visible
        # Update overlay positions (shows/hides sidebar and open button)
        self._update_overlay_positions()

    def _setup_zoom_callback(self) -> None:
        """Setup JS->Python zoom change callback.
        
        When map zoom changes, JS will call Python with the new zoom level
        and a flag indicating whether it was from UI interaction.
        """
        # TODO: Implement proper Qt signal for zoom changes
        # For now, just set up the JS function placeholder
        js = """
        window.onZoomChanged = function(zoom, fromUI) {
            // Called by map.on('zoom') event in map.html
            // fromUI = true if user caused it (wheel, buttons, etc)
            // fromUI = false if we called map.setZoom() from Python
            console.log('Map zoom:', zoom, 'from UI:', fromUI);
        };
        """
        self.web_view.page().runJavaScript(js)

    def _on_zoom_in(self) -> None:
        """Increase map zoom."""
        self._js("if(window.map) window.map.zoomIn();")

    def _on_zoom_out(self) -> None:
        """Decrease map zoom."""
        self._js("if(window.map) window.map.zoomOut();")
    
    def _update_zoom_slider_from_map(
            self, zoom_level: float
    ) -> None:
        """Update zoom slider to match current map zoom.
        
        Called from:
        - on_map_loaded() for initialization
        - JS zoom event listener (wheel, +/- buttons)
        - _on_zoom_slider_moved() blocks signals to prevent loops
        """
        try:
            # Convert zoom level (0-19) to slider position (0-100)
            zoom_min = 0
            zoom_max = 19
            slider_pos = (
                (zoom_level - zoom_min) / (zoom_max - zoom_min)
            ) ** (1.0 / 1.3)
            slider_value = int(
                max(0, min(100, slider_pos * 100))
            )
            
            # Update slider without triggering sliderMoved signal
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(slider_value)
            self.zoom_slider.blockSignals(False)
            
            self.current_zoom = zoom_level
        except Exception as e:
            print(f"Error updating zoom slider: {e}")
    
    def _on_zoom_slider_pressed(self) -> None:
        """User pressed zoom slider - block signals during drag."""
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.blockSignals(False)  # Re-enable but track state
        self._zoom_slider_user_dragging = True
    
    def _on_zoom_slider_released(self) -> None:
        """User released zoom slider."""
        self._zoom_slider_user_dragging = False
    
    def _on_zoom_slider_moved(self, value: int) -> None:
        """User moved zoom slider (0-100 = full world to street level)."""
        slider_pos = value / 100.0
        zoom_min = 0
        zoom_max = 19
        zoom = zoom_min + (zoom_max - zoom_min) * (slider_pos ** 1.3)
        
        # Only send to map if zoom actually changed significantly
        if abs(zoom - self.current_zoom) > 0.05:
            self._js(f"if(window.map) window.map.setZoom({zoom:.1f});")

    def _update_scale_label(self) -> None:
        """Update scale ruler - dynamic width based on zoom."""
        if not self.map_ready:
            return

        def _apply_scale(result):
            if result is not None:
                try:
                    zoom = float(result)
                    self.current_zoom = zoom
                    
                    # Calculate scale ruler distance
                    import math
                    lat = 55.7558  # Default to Moscow
                    px_per_meter = (
                        256 * (2 ** zoom) * math.cos(
                            math.radians(lat)
                        ) / 40075000
                    )
                    
                    # Target: show distance that looks good visually
                    # Aim for 60-120px on screen
                    target_pixels_min = 60
                    target_pixels_max = 120
                    
                    # Predefined scale steps (nice round numbers)
                    scale_steps = [
                        1, 2, 5, 10, 20, 50, 100, 200, 500,
                        1000, 2000, 5000, 10000, 20000, 50000
                    ]
                    
                    # Find best scale: closest to target range
                    best_scale = 1
                    best_diff = float('inf')
                    target_center = (
                        (target_pixels_min + target_pixels_max) / 2
                    )
                    for scale in scale_steps:
                        pixels = scale * px_per_meter
                        # Prefer scales in middle of range
                        diff = abs(pixels - target_center)
                        if diff < best_diff:
                            best_diff = diff
                            best_scale = scale
                    
                    # Calculate actual pixels for this scale
                    ruler_pixels = int(best_scale * px_per_meter)
                    # Clamp between min and max
                    ruler_pixels = max(40, min(200, ruler_pixels))
                    
                    # Format label
                    if best_scale >= 1000:
                        label = f"{best_scale // 1000}km"
                    else:
                        label = f"{best_scale}m"
                    
                    self.scale_ruler.setText(label)
                    
                    # Set line width to calculated size
                    self.scale_ruler_line.setMaximumWidth(ruler_pixels)
                    
                    # Update overlay positions
                    self._update_overlay_positions()
                except Exception as e:
                    print(f"Scale update error: {e}")

        js = (
            "(function(){ if(!window.map) return null; "
            "return window.map.getZoom(); })();"
        )
        self.web_view.page().runJavaScript(js, _apply_scale)
    
    def _update_overlay_positions(self) -> None:
        """Update positions of overlay controls."""
        if not hasattr(self, 'map_frame'):
            return
        
        map_w = self.map_frame.width()
        map_h = self.map_frame.height()
        
        # Position sidebar at left edge (overlay, full height, with margin)
        if self.sidebar_visible:
            self.sidebar.move(8, 8)  # Margin from top-left
            self.sidebar.resize(self.sidebar.width(), map_h - 16)  # Margin
            self.sidebar.show()
            self.sidebar_open_btn.hide()
        else:
            self.sidebar.move(-self.sidebar.width(), 0)
            # Show open button at top-left
            self.sidebar_open_btn.setParent(self.map_frame)
            self.sidebar_open_btn.move(8, 8)
            self.sidebar_open_btn.show()
        
        # Position zoom controls at right-center (overlay)
        if hasattr(self, 'zoom_slider'):
            zoom_container = self.zoom_slider.parent()
            if zoom_container:
                zoom_h = zoom_container.height()
                zoom_x = map_w - 70  # Right edge with margin
                zoom_y = max(20, (map_h - zoom_h) // 2)
                zoom_container.move(zoom_x, zoom_y)
                zoom_container.raise_()

    def restart_agent(self) -> None:
        """Reset agent."""
        self.agent_id = None
        self.status_text.clear()
        self.restart_btn.setEnabled(False)

    def on_map_loaded(self, ok: bool) -> None:
        """Map loaded; restore data and start polling."""
        self.map_ready = ok
        if not ok:
            self.bounds_label.setText("[map failed to load]")
            return
        
        # Initialize zoom bounds and slider from current map zoom
        def _init_zoom_bounds(zoom_result):
            if zoom_result is not None:
                try:
                    initial_zoom = float(zoom_result)
                    self.initial_zoom = initial_zoom
                    self.zoom_min = max(0, 0.2 * initial_zoom)
                    self.zoom_max = min(21, 5.0 * initial_zoom)
                    
                    # Update slider via the single sync function
                    self._update_zoom_slider_from_map(initial_zoom)
                except Exception as e:
                    print(f"Failed to init zoom bounds: {e}")
        
        # Setup JS->Python zoom callback
        js_setup = """
        window.onZoomChanged = function(zoom) {
            // This will be called by map 'zoom' event listener
            // We'll handle it via Qt callback mechanism
        };
        """
        self.web_view.page().runJavaScript(js_setup)
        
        # Get initial zoom and update slider
        js = (
            "(function(){ if(!window.map) return null; "
            "return window.map.getZoom(); })();"
        )
        self.web_view.page().runJavaScript(js, _init_zoom_bounds)
        
        self._bounds_timer = getattr(self, "_bounds_timer", None)
        if not self._bounds_timer:
            self._bounds_timer = QTimer(self)
            self._bounds_timer.timeout.connect(
                self._update_bounds_label
            )
            self._bounds_timer.timeout.connect(
                self._update_scale_label
            )
            self._bounds_timer.start(500)
        if self._graph_geojson is not None:
            code = (
                "window.app && "
                "window.app.setGraphGeoJSON("
                f"{json.dumps(self._graph_geojson)}"
                ");"
            )
            self._js(code)
        if self._routes_ml is not None:
            code = (
                "window.app && "
                "window.app.setRoutes("
                f"{json.dumps(self._routes_ml)}"
                ");"
            )
            self._js(code)
            self._js(
                "window.app && window.app.fitToRoutes();"
            )
        if self._last_agent_pos is not None:
            pos = self._last_agent_pos
            agent_obj = json.dumps(
                {"lat": pos["lat"], "lon": pos["lon"]}
            )
            code = (
                "window.app && "
                "window.app.updateAgent(" + agent_obj + ");"
            )
            self._js(code)

    def _on_ctrl_1(self) -> None:
        """Ctrl+1: Set From point at cursor position."""
        js = "(function(){ return window.lastMousePosition || null; })();"
        
        def callback(result):
            if result:
                self._set_point("from", result["lon"], result["lat"])
        
        self.web_view.page().runJavaScript(js, callback)

    def _on_ctrl_2(self) -> None:
        """Ctrl+2: Set To point at cursor position."""
        js = "(function(){ return window.lastMousePosition || null; })();"
        
        def callback(result):
            if result:
                self._set_point("to", result["lon"], result["lat"])
        
        self.web_view.page().runJavaScript(js, callback)

    def _on_ctrl_3(self) -> None:
        """Ctrl+3: Add Via point at cursor position."""
        js = "(function(){ return window.lastMousePosition || null; })();"
        
        def callback(result):
            if result:
                self._set_point("via", result["lon"], result["lat"])
        
        self.web_view.page().runJavaScript(js, callback)

    def _on_quit(self) -> None:
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NavigationGUI()
    gui.show()
    sys.exit(app.exec_())
