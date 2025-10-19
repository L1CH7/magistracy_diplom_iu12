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
from functools import partial

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QShortcut,
    QMainWindow, QFrame, QMenu, QToolButton,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, QTimer, Qt
from PyQt5.QtGui import QKeySequence, QCursor


class CollapsibleSection(QWidget):
    """Custom collapsible section for logs (Route, Status, Speed)."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._open = False
        self._title = title
        self._content = QWidget()
        self._content.setVisible(self._open)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        self._header_btn = QPushButton(self._header_text(self._title))
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(self._open)
        self._header_btn.clicked.connect(self._toggle)
        self._header_btn.setStyleSheet(
            "text-align: left; font-weight: bold; padding: 6px; "
            "border-radius: 4px; background-color: #e5e7eb; "
            "border: 1px solid #d1d5db;"
        )
        self._layout.addWidget(self._header_btn)
        self._layout.addWidget(self._content)

    def _header_text(self, title: str) -> str:
        return ("▼ " if self._open else "▶ ") + title

    def _toggle(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        self._header_btn.setText(self._header_text(self._title))
        self._header_btn.setChecked(self._open)

    def add_widget(self, w: QWidget) -> None:
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.addWidget(w)


class WebConsolePage(QWebEnginePage):
    """Bridge JS console logs to Python stdout."""

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            lvl = int(level)
        except Exception:
            lvl = level
        print(f"JS[{lvl}] {sourceID}:{lineNumber} {message}")


class NavigationGUI(QMainWindow):
    """Main window: fullscreen map + collapsible left sidebar."""

    def __init__(self, server_url: str = "http://server:8000"):
        super().__init__()
        self.server_url = server_url
        self.agent_id = None
        self.map_ready = False
        self._graph_geojson = None
        self._routes_ml = None
        self._last_agent_pos = None
        self.prev_pos = None
        self.prev_time = None
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

        # ===== SIDEBAR TOGGLE BUTTON =====
        self.sidebar_toggle_btn = QToolButton()
        self.sidebar_toggle_btn.setText("≡")
        self.sidebar_toggle_btn.setMaximumWidth(40)
        self.sidebar_toggle_btn.setMaximumHeight(40)
        self.sidebar_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle_btn.setStyleSheet(
            "QToolButton { background-color: #2563eb; color: white; "
            "border: none; border-radius: 4px; font-weight: bold; font-size: 18px; "
            "padding: 4px; margin: 8px; } "
            "QToolButton:hover { background-color: #1d4ed8; }"
        )
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        self.sidebar_visible = True

        # ===== LEFT SIDEBAR (collapsible) =====
        self.sidebar = QFrame()
        self.sidebar.setStyleSheet(
            "QFrame { background-color: #ffffff; border-right: 1px solid #e5e7eb; "
            "border-radius: 0px; }"
        )
        self.sidebar.setMaximumWidth(350)
        self.sidebar.setMinimumWidth(280)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

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

        main_layout.addWidget(self.sidebar, stretch=0)

        # ===== RIGHT: MAP AREA =====
        map_frame = QFrame()
        map_frame.setStyleSheet("QFrame { background-color: #f3f4f6; }")
        map_layout = QVBoxLayout(map_frame)
        map_layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView()
        map_layout.addWidget(self.web_view)

        main_layout.addWidget(map_frame, stretch=1)

        # ===== OVERLAY CONTROLS ON MAP =====
        # Sidebar toggle button (top-left)
        overlay_top_left = QWidget()
        overlay_top_left.setMaximumSize(50, 50)
        overlay_top_left.setStyleSheet("background-color: transparent;")
        overlay_top_left_layout = QVBoxLayout(overlay_top_left)
        overlay_top_left_layout.setContentsMargins(0, 0, 0, 0)
        overlay_top_left_layout.addWidget(self.sidebar_toggle_btn)

        # Zoom controls (top-right)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setMaximumWidth(40)
        self.zoom_in_btn.setMaximumHeight(40)
        self.zoom_in_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            "border: none; border-radius: 20px; font-weight: bold; "
            "font-size: 16px; } "
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)

        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setMaximumWidth(40)
        self.zoom_out_btn.setMaximumHeight(40)
        self.zoom_out_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; "
            "border: none; border-radius: 20px; font-weight: bold; "
            "font-size: 16px; } "
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)

        overlay_top_right = QWidget()
        overlay_top_right.setMaximumSize(50, 100)
        overlay_top_right.setStyleSheet("background-color: transparent;")
        overlay_top_right_layout = QVBoxLayout(overlay_top_right)
        overlay_top_right_layout.setContentsMargins(0, 0, 0, 0)
        overlay_top_right_layout.addWidget(self.zoom_in_btn)
        overlay_top_right_layout.addWidget(self.zoom_out_btn)

        # Scale widget (bottom-left)
        self.scale_label = QLabel("Zoom: --")
        self.scale_label.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0.95); "
            "padding: 6px 10px; border-radius: 4px; "
            "border: 1px solid #d1d5db; font-size: 11px; "
            "font-family: monospace;"
        )

        # Add overlay widgets to map frame with overlays
        # We need to create a wrapper that allows overlaying
        map_wrapper = QFrame()
        map_wrapper_layout = QHBoxLayout(map_wrapper)
        map_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        map_wrapper_layout.setSpacing(0)

        # Create a stack for map + overlays
        map_stack = QFrame()
        map_stack_layout = QVBoxLayout(map_stack)
        map_stack_layout.setContentsMargins(0, 0, 0, 0)
        map_stack_layout.setSpacing(0)

        # Top bar with controls
        top_controls = QHBoxLayout()
        top_controls.setContentsMargins(8, 8, 8, 0)
        top_controls.setSpacing(0)
        top_controls.addWidget(self.sidebar_toggle_btn, 0)
        top_controls.addStretch()
        top_controls.addWidget(self.zoom_in_btn, 0)
        top_controls.addWidget(self.zoom_out_btn, 0)
        top_controls.addSpacing(8)

        # Bottom bar with scale
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(8, 0, 8, 8)
        bottom_controls.setSpacing(0)
        bottom_controls.addWidget(self.scale_label, 0)
        bottom_controls.addStretch()

        map_stack_layout.addLayout(top_controls, 0)
        map_stack_layout.addWidget(self.web_view, 1)
        map_stack_layout.addLayout(bottom_controls, 0)

        main_layout.addWidget(map_stack, stretch=1)

        # ===== Load map =====
        self._assets_port = self._start_assets_httpd()
        map_url = QUrl(f"http://127.0.0.1:{self._assets_port}/map.html")
        self.web_view.setPage(WebConsolePage(self.web_view))
        self.web_view.load(map_url)
        self.web_view.loadFinished.connect(self._on_map_html_loaded)
        self.web_view.loadFinished.connect(self.on_map_loaded)

        # ESC to quit
        QShortcut(QKeySequence("Esc"), self, activated=self._on_quit)

    def _start_assets_httpd(self) -> int:
        """Start HTTP server for map.html assets."""
        assets_dir = "/app/src/client/assets"
        handler = partial(SimpleHTTPRequestHandler, directory=assets_dir)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return port

    def _on_map_html_loaded(self, ok: bool) -> None:
        """Inject TILE_URL after map.html loads."""
        if not ok:
            print("ERROR: map.html failed to load")
            return
        code = f"window.TILE_URL = {json.dumps(self._tile_url)};"
        print(f"DEBUG: Injecting TILE_URL: {self._tile_url}")
        self.web_view.page().runJavaScript(code)
        # Setup context menu callback from map right-click
        self._setup_map_context_menu()

    def _setup_map_context_menu(self) -> None:
        """Install JS callback for right-click context menu."""
        js_code = """
window.onMapContextMenu = function(pos) {
    console.log('RightClick at:', pos.lng, pos.lat);
};
"""
        self.web_view.page().runJavaScript(js_code)

    def _show_map_context_menu(self, lng: float, lat: float) -> None:
        """Show context menu for map right-click."""
        menu = QMenu(self)
        action_from = menu.addAction("Set From")
        action_to = menu.addAction("Set To")
        action_via = menu.addAction("Add Via")
        action_clear = menu.addAction("Clear All")

        action_from.triggered.connect(
            lambda: self._set_point("from", lng, lat)
        )
        action_to.triggered.connect(
            lambda: self._set_point("to", lng, lat)
        )
        action_via.triggered.connect(
            lambda: self._set_point("via", lng, lat)
        )
        action_clear.triggered.connect(self._clear_map_markers)

        menu.exec_(QCursor.pos())

    def _set_point(self, point_type: str, lng: float, lat: float) -> None:
        """Set a point on map via context menu."""
        if point_type == "from":
            self.start_lat.setText(f"{lat:.6f}")
            self.start_lon.setText(f"{lng:.6f}")
            code = (
                f"window.app && "
                f"window.app.setStart({{"
                f"lng: {lng}, lat: {lat}"
                f"}});"
            )
            self._js(code)
        elif point_type == "to":
            self.end_lat.setText(f"{lat:.6f}")
            self.end_lon.setText(f"{lng:.6f}")
            code = (
                f"window.app && "
                f"window.app.setEnd({{"
                f"lng: {lng}, lat: {lat}"
                f"}});"
            )
            self._js(code)
        elif point_type == "via":
            code = (
                f"window.app && "
                f"window.app.addVia({{"
                f"lng: {lng}, lat: {lat}"
                f"}});"
            )
            self._js(code)

    def _clear_map_markers(self) -> None:
        """Clear all map markers."""
        self._js("window.app && window.app.clearAllMarkers();")

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
        """Toggle sidebar visibility with animation."""
        self.sidebar_visible = not self.sidebar_visible
        self.sidebar.setVisible(self.sidebar_visible)
        # Update button appearance
        self.sidebar_toggle_btn.setText(
            "≡" if self.sidebar_visible else "⋮"
        )

    def _on_zoom_in(self) -> None:
        """Increase map zoom."""
        self._js("if(window.map) window.map.zoomIn();")

    def _on_zoom_out(self) -> None:
        """Decrease map zoom."""
        self._js("if(window.map) window.map.zoomOut();")

    def _update_scale_label(self) -> None:
        """Update scale label with current zoom level."""
        if not self.map_ready:
            return

        def _apply_zoom(result):
            if result is not None:
                try:
                    zoom = float(result)
                    self.scale_label.setText(f"Zoom: {zoom:.1f}")
                except Exception:
                    pass

        js = (
            "(function(){ if(!window.map) return null; "
            "return window.map.getZoom(); })();"
        )
        self.web_view.page().runJavaScript(js, _apply_zoom)

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

    def _on_quit(self) -> None:
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NavigationGUI()
    gui.show()
    sys.exit(app.exec_())
