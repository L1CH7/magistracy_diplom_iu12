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
    QLineEdit, QPushButton, QTextEdit, QComboBox, QShortcut,
    QWidget as QW,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, QTimer
from PyQt5.QtGui import QKeySequence


class CollapsibleSection(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._open = False
        self._title = title
        self._content = QW()
        self._content.setVisible(self._open)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        self._header_btn = QPushButton(self._header_text(self._title))
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(self._open)
        self._header_btn.clicked.connect(self._toggle)
        self._header_btn.setStyleSheet(
            "text-align: left; font-weight: bold; padding: 6px;"
        )
        self._layout.addWidget(self._header_btn)
        self._layout.addWidget(self._content)

    def _header_text(self, title: str) -> str:
        return ("▼ " if self._open else "▶ ") + title

    def _toggle(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        # update arrow
        self._header_btn.setText(self._header_text(self._title))
        self._header_btn.setChecked(self._open)

    def add_widget(self, w: QWidget) -> None:
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.addWidget(w)


class WebConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            lvl = int(level)
        except Exception:
            lvl = level
        print(f"JS[{lvl}] {sourceID}:{lineNumber} {message}")


class NavigationGUI(QWidget):
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
        # Initialize tile_url early so _start_assets_httpd can access it
        self._tile_url = os.environ.get(
            "TILE_URL",
            "http://server:8000/tiles/osm/{z}/{x}/{y}.png"
        )

        self.setWindowTitle("Navigation MAS Client")
        self.setStyleSheet("background-color: #f0f0f0; color: black;")
        self.setup_ui()
        self.load_graph()

    def setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Start point
        start_frame = QHBoxLayout()
        start_frame.addWidget(QLabel("Start Lat:"))
        self.start_lat = QLineEdit("55.751244")
        start_frame.addWidget(self.start_lat)
        start_frame.addWidget(QLabel("Start Lon:"))
        self.start_lon = QLineEdit("37.618423")
        start_frame.addWidget(self.start_lon)
        layout.addLayout(start_frame)

        # End point
        end_frame = QHBoxLayout()
        end_frame.addWidget(QLabel("End Lat:"))
        self.end_lat = QLineEdit("55.755826")
        end_frame.addWidget(self.end_lat)
        end_frame.addWidget(QLabel("End Lon:"))
        self.end_lon = QLineEdit("37.617300")
        end_frame.addWidget(self.end_lon)
        layout.addLayout(end_frame)

        # K input
        k_frame = QHBoxLayout()
        k_frame.addWidget(QLabel("K routes:"))
        self.k_entry = QLineEdit("1")
        k_frame.addWidget(self.k_entry)
        layout.addLayout(k_frame)

        # Buttons
        btn_frame = QHBoxLayout()
        self.get_route_btn = QPushButton("Get Route")
        self.get_route_btn.clicked.connect(self.get_route)
        btn_frame.addWidget(self.get_route_btn)

        self.start_agent_btn = QPushButton("Start Agent")
        self.start_agent_btn.clicked.connect(self.start_agent)
        self.start_agent_btn.setEnabled(False)
        btn_frame.addWidget(self.start_agent_btn)

        self.view_map_btn = QPushButton("View Map")
        self.view_map_btn.clicked.connect(self.view_map)
        btn_frame.addWidget(self.view_map_btn)

        # Picking buttons: From / To / Via / Clear
        self.pick_from_btn = QPushButton("From")
        self.pick_from_btn.clicked.connect(
            lambda: self._js("window.app && window.app.setPickMode('from');")
        )
        btn_frame.addWidget(self.pick_from_btn)

        self.pick_to_btn = QPushButton("To")
        self.pick_to_btn.clicked.connect(
            lambda: self._js("window.app && window.app.setPickMode('to');")
        )
        btn_frame.addWidget(self.pick_to_btn)

        self.pick_via_btn = QPushButton("Via")
        self.pick_via_btn.clicked.connect(
            lambda: self._js("window.app && window.app.setPickMode('via');")
        )
        btn_frame.addWidget(self.pick_via_btn)

        self.clear_pick_btn = QPushButton("Clear picks")
        self.clear_pick_btn.clicked.connect(
            lambda: self._js("window.app && window.app.clearPicked();")
        )
        btn_frame.addWidget(self.clear_pick_btn)
        layout.addLayout(btn_frame)

        # Collapsible logs (click to open, click again to close)
        # Simple custom sections for better UX
        sections_container = QVBoxLayout()

        self.route_text = QTextEdit()
        self.route_section = CollapsibleSection("Route")
        self.route_section.add_widget(self.route_text)
        sections_container.addWidget(self.route_section)

        self.status_text = QTextEdit()
        self.status_section = CollapsibleSection("Agent Status")
        self.status_section.add_widget(self.status_text)
        sections_container.addWidget(self.status_section)

        self.speed_label = QLabel("Speed: 0 km/h")
        self.speed_section = CollapsibleSection("Speed")
        self.speed_section.add_widget(self.speed_label)
        sections_container.addWidget(self.speed_section)

        layout.addLayout(sections_container)

        # Route selection
        route_frame = QHBoxLayout()
        route_frame.addWidget(QLabel("Select Route:"))
        self.route_combo = QComboBox()
        self.route_combo.addItem("Route 1")
        self.route_combo.currentIndexChanged.connect(self.select_route)
        route_frame.addWidget(self.route_combo)
        layout.addLayout(route_frame)

        # Map bounds display (replaces manual bbox load)
        bounds_frame = QHBoxLayout()
        bounds_frame.addWidget(QLabel("Map bounds:"))
        self.bounds_label = QLabel("[-, -, -, -]")
        bounds_frame.addWidget(self.bounds_label)
        layout.addLayout(bounds_frame)

        # Control buttons
        ctrl_frame = QHBoxLayout()
        self.restart_btn = QPushButton("Restart Agent")
        self.restart_btn.clicked.connect(self.restart_agent)
        self.restart_btn.setEnabled(False)
        ctrl_frame.addWidget(self.restart_btn)
        self.quit_btn = QPushButton("Quit")
        self.quit_btn.clicked.connect(self.close)
        ctrl_frame.addWidget(self.quit_btn)
        layout.addLayout(ctrl_frame)

        # Map (MapLibre GL HTML) — occupy most of the screen
        layout.addWidget(QLabel("Map:"))
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view, stretch=1)
        # Start a tiny local HTTP server to serve map.html, avoiding
        # file:// origin CORS restrictions in QtWebEngine
        self._assets_port = self._start_assets_httpd()
        map_url = QUrl(f"http://127.0.0.1:{self._assets_port}/map.html")
        # Console log hook to debug tile/GL errors.
        # IMPORTANT: set the custom page BEFORE loading the URL.
        self.web_view.setPage(WebConsolePage(self.web_view))
        self.web_view.load(map_url)
        self.web_view.loadFinished.connect(self._on_map_html_loaded)
        self.web_view.loadFinished.connect(self.on_map_loaded)

        self.setLayout(layout)
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
        """Inject TILE_URL as window variable after map.html loads."""
        if not ok:
            print("ERROR: map.html failed to load")
            return
        # Inject window.TILE_URL before map accesses it
        code = f"window.TILE_URL = {json.dumps(self._tile_url)};"
        print(f"DEBUG: Injecting TILE_URL: {self._tile_url}")
        self.web_view.page().runJavaScript(code)

    def _js(self, code: str) -> None:
        if self.map_ready:
            self.web_view.page().runJavaScript(code)

    def load_graph(self) -> None:
        def worker():
            graph_nodes = {}
            graph_edges = []
            try:
                resp = requests.get(f"{self.server_url}/graph", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    graph_nodes.update({n['id']: n for n in data['nodes']})
                    graph_edges = data['edges']
            except Exception:
                pass
            features = []
            for edge in graph_edges[:5000]:
                u, v = edge['u'], edge['v']
                if u in graph_nodes and v in graph_nodes:
                    u_data, v_data = graph_nodes[u], graph_nodes[v]
                    features.append({
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [u_data['lon'], u_data['lat']],
                                [v_data['lon'], v_data['lat']],
                            ],
                        },
                    })
            graph_geojson = {"type": "FeatureCollection", "features": features}

            def apply():
                self._graph_geojson = graph_geojson
                code = (
                    "window.app && window.app.setGraphGeoJSON("
                    f"{json.dumps(graph_geojson)}"
                    ");"
                )
                self._js(code)
                # Auto-fit to graph extent so user sees lines even if
                # tiles fail
                self._js("window.app && window.app.fitToGraph();")

            QTimer.singleShot(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def get_route(self) -> None:
        try:
            start_lat = float(self.start_lat.text())
            start_lon = float(self.start_lon.text())
            end_lat = float(self.end_lat.text())
            end_lon = float(self.end_lon.text())
        except ValueError:
            self.status_text.append("Invalid coordinates")
            return
        k_val = (
            int(self.k_entry.text()) if self.k_entry.text().isdigit() else 1
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
                    f"{self.server_url}/route", json=req, timeout=20
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
                    self.routes = data['routes']
                    self.current_route_index = 0
                    self.route_text.clear()
                    for i, r in enumerate(self.routes):
                        self.route_text.append(
                            f"Route {i+1}: Nodes {len(r['nodes'])}, "
                            f"Dist {r['total_distance']:.2f}m, "
                            f"Time {r['estimated_time']:.2f}s"
                        )
                    self.start_agent_btn.setEnabled(True)
                    colors = [
                        '#2563eb', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6'
                    ]
                    ml_routes = []
                    for i, r in enumerate(self.routes):
                        coords = [[p['lon'], p['lat']] for p in r['positions']]
                        ml_routes.append({
                            'id': f'route{i+1}',
                            'coords': coords,
                            'color': colors[i % len(colors)],
                        })
                    self._routes_ml = ml_routes
                    code = (
                        "window.app && window.app.setRoutes("
                        f"{json.dumps(ml_routes)}"
                        ");"
                    )
                    self._js(code)
                    self._js("window.app && window.app.fitToRoutes();")
                    self.route_combo.clear()
                    self.route_combo.addItems(
                        [f"Route {i+1}" for i in range(len(self.routes))]
                    )
                    self.route_combo.setCurrentText("Route 1")
                self.get_route_btn.setEnabled(True)

            QTimer.singleShot(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def start_agent(self) -> None:
        if not hasattr(self, 'routes') or not self.routes:
            self.status_text.append("Get routes first")
            return
        try:
            req = {
                "route_nodes": self.routes[self.current_route_index]['nodes'],
                "params": {
                    "max_speed": 50.0, "power": 100.0,
                    "length": 5.0, "width": 2.0,
                },
            }
            resp = requests.post(
                f"{self.server_url}/agent/start", json=req, timeout=10
            )
            if resp.status_code == 200:
                state = resp.json()
                self.agent_id = state['agent_id']
                self.status_text.clear()
                self.status_text.append(
                    f"Agent {self.agent_id} started at node {state['index']}"
                )
                self.restart_btn.setEnabled(True)
                threading.Thread(
                    target=self.simulate_agent, daemon=True
                ).start()
            else:
                self.status_text.append(f"Failed to start agent: {resp.text}")
        except Exception as e:
            self.status_text.append(str(e))

    def simulate_agent(self) -> None:
        while self.agent_id:
            try:
                resp = requests.post(
                    f"{self.server_url}/agent/{self.agent_id}/step", timeout=10
                )
                if resp.status_code == 200:
                    state = resp.json()
                    current_time = time.time()
                    if self.prev_pos and self.prev_time:
                        lat_diff = (
                            state['position']['lat'] - self.prev_pos['lat']
                        )
                        lon_diff = (
                            state['position']['lon'] - self.prev_pos['lon']
                        )
                        dist = ((lat_diff**2 + lon_diff**2)**0.5) * 111320
                        dt = current_time - self.prev_time
                        if dt > 0:
                            speed = min(dist / dt * 3.6, 120.0)
                            self.speed_label.setText(
                                f"Speed: {speed:.2f} km/h"
                            )
                    self.prev_pos = state['position']
                    self.prev_time = current_time
                    self.status_text.clear()
                    self.status_text.append(
                        f"Agent {state['agent_id']} at index "
                        f"{state['index']}, pos: {state['position']}, "
                        f"done: {state['done']}"
                    )
                    pos = state['position']
                    self._last_agent_pos = pos
                    agent_obj = json.dumps({
                        'lat': pos['lat'], 'lon': pos['lon']
                    })
                    code = (
                        "window.app && window.app.updateAgent(" +
                        agent_obj + ");"
                    )
                    self._js(code)
                    if state['done']:
                        break
                else:
                    self.status_text.append(f"Step failed: {resp.text}")
                    break
            except Exception as e:
                self.status_text.append(f"Error: {str(e)}")
                break
            time.sleep(0.1)

    def _update_bounds_label(self) -> None:
        # Pull bounds from MapLibre and display as
        # [min_lon, min_lat, max_lon, max_lat]
        if not self.map_ready:
            return

        def _apply_bounds(result):
            # result expected as {west, south, east, north}
            if not result or not isinstance(result, dict):
                return
            try:
                bbox = [
                    float(result.get('west')),
                    float(result.get('south')),
                    float(result.get('east')),
                    float(result.get('north')),
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

    def generate_map(self) -> None:
        # Rendering is driven from JS; no-op here.
        pass

    def restart_agent(self) -> None:
        self.agent_id = None
        self.status_text.clear()
        self.restart_btn.setEnabled(False)

    def select_route(self) -> None:
        selected = self.route_combo.currentText()
        if selected:
            index = int(selected.split()[1]) - 1
            self.current_route_index = index
            self.generate_map()

    def view_map(self) -> None:
        self.generate_map()

    def on_map_loaded(self, ok: bool) -> None:
        self.map_ready = ok
        if not ok:
            # Visual hint when map fails to load
            self.bounds_label.setText("[map failed to load]")
            return
        # start periodic bounds label refresh
        self._bounds_timer = getattr(self, '_bounds_timer', None)
        if not self._bounds_timer:
            self._bounds_timer = QTimer(self)
            self._bounds_timer.timeout.connect(self._update_bounds_label)
            self._bounds_timer.start(500)
        if self._graph_geojson is not None:
            code = (
                "window.app && window.app.setGraphGeoJSON("
                f"{json.dumps(self._graph_geojson)}"
                ");"
            )
            self._js(code)
        if self._routes_ml is not None:
            code = (
                "window.app && window.app.setRoutes("
                f"{json.dumps(self._routes_ml)}"
                ");"
            )
            self._js(code)
            self._js("window.app && window.app.fitToRoutes();")
        if self._last_agent_pos is not None:
            pos = self._last_agent_pos
            agent_obj = json.dumps({'lat': pos['lat'], 'lon': pos['lon']})
            code = "window.app && window.app.updateAgent(" + agent_obj + ");"
            self._js(code)

    def run(self) -> None:
        self.show()

    def _on_quit(self) -> None:
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NavigationGUI()
    gui.run()
    sys.exit(app.exec_())
