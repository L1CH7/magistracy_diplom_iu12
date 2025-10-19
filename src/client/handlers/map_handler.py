"""Map initialization and event handling."""
import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs

from PyQt5.QtWidgets import QMenu
from PyQt5.QtCore import QTimer, QUrl, pyqtSlot

# Handle both relative and absolute imports
try:
    from ..models import NavigationState
except ImportError:
    from models import NavigationState


class ZoomAPIHandler(SimpleHTTPRequestHandler):
    """HTTP handler for zoom API calls from JavaScript."""
    
    gui_instance = None  # Set by NavigationState
    
    def do_GET(self):
        """Handle zoom GET request."""
        if self.path.startswith('/zoom?'):
            qs = parse_qs(self.path.split('?')[1])
            try:
                zoom_value = float(qs.get('value', [0])[0])
                if self.gui_instance:
                    self.gui_instance._handle_zoom_from_js(zoom_value)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception as e:
                print(f"Zoom API error: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class MapHandler:
    """Handles map initialization, events, and context menu."""
    
    def __init__(self, gui_instance, nav_state: NavigationState):
        self.gui = gui_instance
        self.nav_state = nav_state
        self._tile_url = nav_state.tile_url
        self._context_menu_timer = None
        
        # TODO: Connect zoom_changed signal to update map zoom level
        # self.nav_state.zoom_changed.connect(self._on_zoom_changed)
        
        # TODO: Connect map JavaScript events to nav_state signals
        # - Emit zoom_changed when user zooms with scroll/buttons
        # - Emit bounds_changed when map pans
        # - Emit map_center_moved when map center changes
    
    def start_assets_server(self) -> int:
        """Start HTTP server for map.html assets + zoom API."""
        assets_dir = "/app/src/client/assets"
        handler = partial(ZoomAPIHandler, directory=assets_dir)
        # Store reference to this GUI instance in handler
        ZoomAPIHandler.gui_instance = self.gui
        httpd = ThreadingHTTPServer(("127.0.0.1", 9999), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return port
    
    def on_map_html_loaded(self) -> None:
        """Inject TILE_URL and setup callbacks after map.html loads."""
        code = f"window.TILE_URL = {json.dumps(self._tile_url)};"
        print(f"DEBUG: Injecting TILE_URL: {self._tile_url}")
        self.gui.web_view.page().runJavaScript(code)
        
        # Setup context menu callback
        self.setup_map_context_menu()
    
    def setup_map_context_menu(self) -> None:
        """Install JS callback for right-click context menu."""
        js_code = """
        window.lastContextMenuPos = null;
        window.lastContextMenuProcessed = false;
        
        window.onMapContextMenu = function(pos) {
            console.log('RightClick at:', pos.lon, pos.lat);
            window.lastContextMenuPos = pos;
            window.lastContextMenuProcessed = false;
        };
        """
        self.gui.web_view.page().runJavaScript(js_code)
        
        # Start polling timer
        self._context_menu_timer = QTimer()
        self._context_menu_timer.timeout.connect(self._poll_context_menu_pos)
        self._context_menu_timer.start(20)
    
    def _poll_context_menu_pos(self) -> None:
        """Poll for right-click position from JavaScript."""
        self.gui.web_view.page().runJavaScript(
            "JSON.stringify(window.lastContextMenuPos)",
            lambda result: self._on_context_menu_pos_received(result)
        )
    
    def _on_context_menu_pos_received(self, result: str) -> None:
        """Handle context menu position received from JS."""
        if not result or result == "null":
            return
        
        try:
            pos = json.loads(result)
            if pos and not getattr(self, '_context_menu_shown', False):
                self._context_menu_shown = True
                self.show_map_context_menu(pos.get('lon', 0), pos.get('lat', 0))
                # Reset the flag after menu closes
                QTimer.singleShot(500, lambda: setattr(self, '_context_menu_shown', False))
        except Exception as e:
            print(f"Error parsing context menu position: {e}")
    
    def show_map_context_menu(self, lon: float, lat: float) -> None:
        """Show context menu for map right-click."""
        menu = QMenu(self.gui)
        menu.setWindowOpacity(0.95)
        menu.setMinimumWidth(180)
        
        action_from = menu.addAction("Set From Point")
        action_to = menu.addAction("Set To Point")
        
        action_via = None
        if len(self.gui.points) >= 2:
            action_via = menu.addAction("Add Via Point")
        
        menu.addSeparator()
        action_clear = menu.addAction("Clear All")
        
        action = menu.exec_(self.gui.mapToGlobal(self.gui.pos()))
        
        if action == action_from:
            self.gui._set_point("from", lon, lat)
        elif action == action_to:
            self.gui._set_point("to", lon, lat)
        elif action_via and action == action_via:
            self.gui._set_point("via", lon, lat)
        elif action == action_clear:
            self.gui._clear_all_points()
        
        # Emit signal
        self.nav_state.map_clicked.emit(lon, lat)
    
    @pyqtSlot(float, float)
    def _on_map_clicked(self, lon: float, lat: float) -> None:
        """Handle map click signal."""
        pass  # For future expansion
