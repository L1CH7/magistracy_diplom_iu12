import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit, QComboBox
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, QUrlQuery
import requests
import threading
import time


class NavigationGUI(QWidget):
    def __init__(self, server_url="http://server:8000"):
        super().__init__()
        self.server_url = server_url
        self.agent_id = None
        self.map_ready = False
        self._graph_geojson = None
        self._routes_ml = None
        self._last_agent_pos = None
        self.setWindowTitle("Navigation MAS Client")
        self.setStyleSheet("background-color: #f0f0f0; color: black;")
        self.setup_ui()
        self.load_graph()
        self.prev_pos = None
        self.prev_time = None

    def setup_ui(self):
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

        layout.addLayout(btn_frame)

        # Route display
        layout.addWidget(QLabel("Route:"))
        self.route_text = QTextEdit()
        layout.addWidget(self.route_text)

        # Agent status
        layout.addWidget(QLabel("Agent Status:"))
        self.status_text = QTextEdit()
        layout.addWidget(self.status_text)

        # Speed display
        self.speed_label = QLabel("Speed: 0 km/h")
        layout.addWidget(self.speed_label)

        # Route selection
        route_frame = QHBoxLayout()
        route_frame.addWidget(QLabel("Select Route:"))
        self.route_combo = QComboBox()
        self.route_combo.addItem("Route 1")
        self.route_combo.currentIndexChanged.connect(self.select_route)
        route_frame.addWidget(self.route_combo)
        layout.addLayout(route_frame)

        # OSM Load
        osm_frame = QHBoxLayout()
        osm_frame.addWidget(QLabel("Bbox (min_lon min_lat max_lon max_lat):"))
        self.bbox_entry = QLineEdit("37.4 55.6 37.8 55.9")
        osm_frame.addWidget(self.bbox_entry)
        self.load_osm_btn = QPushButton("Load OSM")
        self.load_osm_btn.clicked.connect(self.load_osm)
        osm_frame.addWidget(self.load_osm_btn)
        layout.addLayout(osm_frame)

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

        # Map (MapLibre GL HTML)
        layout.addWidget(QLabel("Map:"))
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
        # Load local HTML asset with tile URL query param for MapLibre
        map_url = QUrl.fromLocalFile("/app/src/client/assets/map.html")
        q = QUrlQuery()
        tile_url = os.environ.get(
            "TILE_URL",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        q.addQueryItem("tile", tile_url)
        map_url.setQuery(q)
        self.web_view.load(map_url)
        self.web_view.loadFinished.connect(self.on_map_loaded)

        self.setLayout(layout)

    def load_graph(self):
        try:
            resp = requests.get(f"{self.server_url}/graph")
            if resp.status_code == 200:
                data = resp.json()
                graph_nodes = {n['id']: n for n in data['nodes']}
                graph_edges = data['edges']
            else:
                graph_nodes = {}
                graph_edges = []
        except Exception:
            graph_nodes = {}
            graph_edges = []
        # Build GeoJSON for graph edges and push into MapLibre
        features = []
        # larger cap; MapLibre handles lots of lines
        for e in graph_edges[:5000]:
            u, v = e['u'], e['v']
            if u in graph_nodes and v in graph_nodes:
                u_data, v_data = graph_nodes[u], graph_nodes[v]
                features.append({
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [u_data['lon'], u_data['lat']],
                            [v_data['lon'], v_data['lat']]
                        ]
                    }
                })
        graph_geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        self._graph_geojson = graph_geojson
        if self.map_ready:
            self.web_view.page().runJavaScript(
                f"window.app && window.app.setGraphGeoJSON({graph_geojson});"
            )

    def get_route(self):
        try:
            start_lat = float(self.start_lat.text())
            start_lon = float(self.start_lon.text())
            end_lat = float(self.end_lat.text())
            end_lon = float(self.end_lon.text())
            req = {
                "start": {"lat": start_lat, "lon": start_lon},
                "end": {"lat": end_lat, "lon": end_lon},
                "k": int(self.k_entry.text()) if self.k_entry.text().isdigit()
                else 1
            }
            resp = requests.post(f"{self.server_url}/route", json=req)
            if resp.status_code == 200:
                data = resp.json()
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
                # Push routes to MapLibre
                ml_routes = []
                colors = [
                    '#2563eb', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6'
                ]
                for i, r in enumerate(self.routes):
                    coords = [[p['lon'], p['lat']] for p in r['positions']]
                    ml_routes.append({
                        'id': f'route{i+1}',
                        'coords': coords,
                        'color': colors[i % len(colors)]
                    })
                self._routes_ml = ml_routes
                if self.map_ready:
                    self.web_view.page().runJavaScript(
                        f"window.app && window.app.setRoutes({ml_routes});"
                    )
                    self.web_view.page().runJavaScript(
                        "window.app && window.app.fitToRoutes();"
                    )
                self.route_combo.clear()
                self.route_combo.addItems(
                    [f"Route {i+1}" for i in range(len(self.routes))]
                )
                self.route_combo.setCurrentText("Route 1")
            else:
                self.status_text.append(f"Failed to get route: {resp.text}")
        except ValueError:
            self.status_text.append("Invalid coordinates")
        except Exception as e:
            self.status_text.append(str(e))

    def start_agent(self):
        if not hasattr(self, 'routes') or not self.routes:
            self.status_text.append("Get routes first")
            return
        try:
            req = {
                "route_nodes": self.routes[self.current_route_index]['nodes'],
                "params": {
                    "max_speed": 50.0, "power": 100.0,
                    "length": 5.0, "width": 2.0
                }
            }
            resp = requests.post(f"{self.server_url}/agent/start", json=req)
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

    def simulate_agent(self):
        while self.agent_id:
            try:
                resp = requests.post(
                    f"{self.server_url}/agent/{self.agent_id}/step"
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
                            speed = dist / dt * 3.6
                            speed = min(speed, 120.0)
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
                    # Update agent smoothly on map
                    pos = state['position']
                    js = (
                        "window.app && window.app.updateAgent({" +
                        f"'lat': {pos['lat']}, 'lon': {pos['lon']}" + "});"
                    )
                    self._last_agent_pos = pos
                    if self.map_ready:
                        self.web_view.page().runJavaScript(js)
                    if state['done']:
                        break
                else:
                    self.status_text.append(f"Step failed: {resp.text}")
                    break
            except Exception as e:
                self.status_text.append(f"Error: {str(e)}")
                break
            time.sleep(0.1)

    def load_osm(self):
        try:
            bbox_str = self.bbox_entry.text()
            bbox = [float(x) for x in bbox_str.split()]
            if len(bbox) != 4:
                raise ValueError("Need 4 values")
            req = {"bbox": bbox}
            resp = requests.post(f"{self.server_url}/osm/load", json=req)
            if resp.status_code == 200:
                result = resp.json()
                self.status_text.append(result['message'])
                self.load_graph()  # Reload graph
            else:
                self.status_text.append(f"Failed to load OSM: {resp.text}")
        except ValueError:
            self.status_text.append("Invalid bbox format")
        except Exception as e:
            self.status_text.append(str(e))

    def generate_map(self):
        # Deprecated: Map rendering is driven directly in MapLibre via JS API
        pass

    def restart_agent(self):
        self.agent_id = None
        self.status_text.clear()
        self.restart_btn.setEnabled(False)

    def select_route(self):
        selected = self.route_combo.currentText()
        if selected:
            index = int(selected.split()[1]) - 1
            self.current_route_index = index
            self.generate_map()

    def view_map(self):
        self.generate_map()

    def on_map_loaded(self, ok: bool):
        self.map_ready = ok
        if not ok:
            return
        # push latest known data
        if self._graph_geojson is not None:
            js = (
                "window.app && window.app.setGraphGeoJSON(" +
                f"{self._graph_geojson}" + ");"
            )
            self.web_view.page().runJavaScript(js)
        if self._routes_ml is not None:
            self.web_view.page().runJavaScript(
                f"window.app && window.app.setRoutes({self._routes_ml});"
            )
            self.web_view.page().runJavaScript(
                "window.app && window.app.fitToRoutes();"
            )
        if self._last_agent_pos is not None:
            pos = self._last_agent_pos
            js = (
                "window.app && window.app.updateAgent({" +
                f"'lat': {pos['lat']}, 'lon': {pos['lon']}" + "});"
            )
            self.web_view.page().runJavaScript(js)

    def run(self):
        # Only show the window; the QApplication event loop
        # is started once in the __main__ section below.
        self.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = NavigationGUI()
    gui.run()
    sys.exit(app.exec_())
