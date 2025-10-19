"""Main application window with full UI and signal/slot connections."""
import os
import json
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel
)
from PyQt5.QtCore import QTimer, pyqtSlot

from ..models import NavigationState
from ..services import APIClient
from ..config.ui_config import (
    SIDEBAR_WIDTH, WINDOW_WIDTH, WINDOW_HEIGHT
)
from .widgets import (
    MapWidget, PointsPanel, ControlsPanel, StatusPanel,
    CollapsibleSection
)


class ZoomAPIHandler(SimpleHTTPRequestHandler):
    """HTTP handler for /api/zoom endpoint."""

    main_window = None  # Set by MainWindow

    def do_GET(self):
        """Handle zoom API requests."""
        path = self.path.split('?')[0]
        
        if path == '/api/zoom':
            params = parse_qs(self.path.split('?')[1] if '?' in self.path else '')
            if 'value' in params and self.main_window:
                try:
                    zoom = float(params['value'][0])
                    self.main_window._on_zoom_from_js(zoom)
                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'OK')
                    return
                except Exception:
                    pass
        
        self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress HTTP server logging."""
        pass


class MainWindow(QMainWindow):
    """Main application window with map and controls.
    
    Architecture:
    - NavigationState: Central state (model)
    - APIClient: Async HTTP operations (services)
    - UI Panels: Dumb views that react to state signals
    - MainWindow: Controller that connects everything via signals/slots
    
    All long-running operations (HTTP, graph loading) are in separate threads.
    UI remains responsive always.
    """

    def __init__(self, server_url: str = "http://server:8000"):
        """Initialize main window.
        
        Args:
            server_url: Backend server URL
        """
        super().__init__()
        
        self.server_url = server_url
        self.agent_id = None
        self.routes = []
        self.current_route_index = 0
        self.prev_pos = None
        self.prev_time = None
        self.simulate_thread = None
        
        # Color palette for via points
        self.color_palette = [
            "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
            "#ec4899", "#a855f7", "#0ea5e9", "#10b981"
        ]
        self._color_idx = 0
        
        # Initialize core components
        self.state = NavigationState()
        self.api_client = APIClient(server_url)
        
        # Setup window
        self.setWindowTitle("Navigation MAS — Modular Architecture")
        self.setGeometry(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.showMaximized()
        
        # Setup UI
        self._setup_ui()
        
        # Connect signals
        self._connect_signals()
        
        # Start HTTP server for zoom API
        self._start_zoom_http_server()
        
        # Load graph on startup
        QTimer.singleShot(500, self._on_load_graph)
    
    def _setup_ui(self) -> None:
        """Setup user interface layout."""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # === LEFT SIDEBAR (collapsible) ===
        self.sidebar = QFrame()
        self.sidebar.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; "
            "border-radius: 8px; }"
        )
        self.sidebar.setMaximumWidth(SIDEBAR_WIDTH)
        self.sidebar.setMinimumWidth(280)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)
        
        # Title
        title = QLabel("Navigation MAS")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        sidebar_layout.addWidget(title)
        
        # Controls panel
        self.controls_panel = ControlsPanel(self.state)
        sidebar_layout.addWidget(self.controls_panel)
        
        # Points panel (collapsible)
        points_section = CollapsibleSection("Selected Points")
        self.points_panel = PointsPanel(self.state)
        points_section.add_widget(self.points_panel)
        sidebar_layout.addWidget(points_section)
        
        # Status panel
        self.status_panel = StatusPanel(self.state)
        sidebar_layout.addWidget(self.status_panel)
        
        main_layout.addWidget(self.sidebar, 0)
        
        # === RIGHT: MAP ===
        self.map_widget = MapWidget()
        main_layout.addWidget(self.map_widget, 1)
        
        # Load map HTML
        map_html = os.path.join(
            os.path.dirname(__file__), '../../assets/map.html'
        )
        if os.path.exists(map_html):
            self.map_widget.load_map(map_html)
    
    def _connect_signals(self) -> None:
        """Connect all signals and slots.
        
        This is where the magic happens - we wire up the entire
        signal/slot system for reactive, efficient updates.
        """
        # === Controls → Actions ===
        self.controls_panel.load_graph_clicked.connect(self._on_load_graph)
        self.controls_panel.calculate_route_clicked.connect(
            self._on_calculate_route
        )
        self.controls_panel.start_agent_clicked.connect(self._on_start_agent)
        self.controls_panel.restart_agent_clicked.connect(
            self._on_restart_agent
        )
        self.controls_panel.clear_clicked.connect(self._on_clear_points)
        
        # === Map → Context Menu ===
        self.map_widget.context_menu_requested.connect(
            self._on_map_right_click
        )
        
        # === State → UI Updates (automatic via signals) ===
        # (handled by individual panels in their __init__)
        
        # === APIClient responses ===
        self.api_client.graph_loaded.connect(self._on_graph_loaded)
        self.api_client.graph_load_failed.connect(self._on_graph_load_failed)
        self.api_client.route_calculated.connect(self._on_route_calculated)
        self.api_client.route_calc_failed.connect(self._on_route_calc_failed)
    
    @pyqtSlot()
    def _on_load_graph(self) -> None:
        """Load graph from server."""
        self.state.start_operation("Loading graph")
        self.api_client.load_graph(
            os.path.join(os.path.dirname(__file__), '../../data/osm_data.json')
        )
    
    @pyqtSlot(dict)
    def _on_graph_loaded(self, graph_data: dict) -> None:
        """Handle graph loaded.
        
        Args:
            graph_data: Loaded graph dictionary
        """
        self.state.set_status("Graph loaded, ready to calculate routes")
        self.state.complete_operation(True)
        
        # Extract GeoJSON and display on map
        features = []
        nodes = {n['id']: n for n in graph_data.get('nodes', [])}
        
        for edge in graph_data.get('edges', [])[:5000]:  # Limit for performance
            u, v = edge['u'], edge['v']
            if u in nodes and v in nodes:
                u_data, v_data = nodes[u], nodes[v]
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': [[u_data['lon'], u_data['lat']],
                                        [v_data['lon'], v_data['lat']]]
                    }
                })
        
        geojson = {'type': 'FeatureCollection', 'features': features}
        self.map_widget.execute_js(
            f"if (window.app) window.app.setGraphGeoJSON({json.dumps(geojson)});"
        )
        self.map_widget.execute_js(
            "if (window.app) window.app.fitToGraph();"
        )
    
    @pyqtSlot(str)
    def _on_graph_load_failed(self, error: str) -> None:
        """Handle graph load failure.
        
        Args:
            error: Error message
        """
        self.state.report_error(f"Failed to load graph: {error}")
    
    @pyqtSlot()
    def _on_calculate_route(self) -> None:
        """Calculate route from controls."""
        start = self.controls_panel.get_start_coords()
        end = self.controls_panel.get_end_coords()
        k_routes = self.controls_panel.get_k_routes()
        
        if not start or not end:
            self.state.report_error("Invalid coordinates")
            return
        
        # Add start and end points to state
        self.state.clear_points()
        self.state.add_point('start', start[0], start[1])
        self.state.add_point('end', end[0], end[1])
        
        # Request route
        waypoints = self.state.get_waypoints()
        self.state.start_operation(f"Calculating {k_routes} route(s)")
        self.api_client.calculate_route(waypoints, k_routes)
    
    @pyqtSlot(object)
    def _on_route_calculated(self, route) -> None:
        """Handle route calculated.
        
        Args:
            route: Route object
        """
        self.routes.append(route)
        self.state.set_route(
            route.nodes, route.edges, route.distance_m, route.duration_s,
            route.coordinates
        )
        self.state.complete_operation(True)
        self.controls_panel.enable_agent_buttons(True)
        
        # Show route on map
        if route.coordinates:
            self.map_widget.show_route(route.coordinates)
    
    @pyqtSlot(str)
    def _on_route_calc_failed(self, error: str) -> None:
        """Handle route calculation failure.
        
        Args:
            error: Error message
        """
        self.state.report_error(f"Route calculation failed: {error}")
    
    @pyqtSlot()
    def _on_start_agent(self) -> None:
        """Start agent simulation."""
        if not self.routes:
            self.state.report_error("Calculate a route first")
            return
        
        route = self.routes[self.current_route_index]
        self.state.set_status(f"Starting agent on route {len(route.nodes)} nodes")
        # TODO: Implement agent start when backend available
    
    @pyqtSlot()
    def _on_restart_agent(self) -> None:
        """Restart agent simulation."""
        if self.agent_id:
            self.state.set_status("Restarting agent...")
            # TODO: Implement agent restart when backend available
    
    @pyqtSlot()
    def _on_clear_points(self) -> None:
        """Clear all points."""
        self.state.clear_points()
        self.map_widget.clear_markers()
        self.state.set_status("Points cleared")
    
    @pyqtSlot(float, float)
    def _on_map_right_click(self, lon: float, lat: float) -> None:
        """Handle right-click on map for point selection.
        
        Args:
            lon: Longitude
            lat: Latitude
        """
        # TODO: Implement context menu for point type selection
        # For now, add as 'via' point
        self.state.add_point('via', lon, lat)
        self.map_widget.add_marker(lon, lat, self.color_palette[
            self._color_idx % len(self.color_palette)
        ], f"Point {len(self.state.get_points())}")
        self._color_idx += 1
    
    def _on_zoom_from_js(self, zoom: float) -> None:
        """Handle zoom change from JS.
        
        Args:
            zoom: New zoom level
        """
        self.state.set_zoom(zoom)
    
    def _start_zoom_http_server(self) -> None:
        """Start HTTP server for zoom API."""
        ZoomAPIHandler.main_window = self
        
        try:
            server = ThreadingHTTPServer(('0.0.0.0', 8888), ZoomAPIHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.state.set_status("Zoom server started on :8888")
        except Exception as e:
            self.state.report_error(f"Failed to start zoom server: {e}")
