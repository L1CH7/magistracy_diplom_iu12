"""Main application window with fullscreen map + overlay sidebar."""
import os
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial

from PyQt5.QtWidgets import QMainWindow, QWidget, QShortcut
from PyQt5.QtCore import QUrl, QTimer
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtGui import QKeySequence

from src.client.ui.widgets.map_widget import MapWidget
from src.client.handlers.zoom_bridge import ZoomBridge
from src.client.handlers.points_bridge import PointsBridge
from src.client.models.points_presenter import PointsPresenter
from src.client.ui.main_window_handlers import MainWindowHandlers
from src.client.ui.main_window_ui import MainWindowUI
from src.utils.logging_config import setup_logging, get_logger


# Setup logging at module level
setup_logging(log_file="logs/navigation_mas.log", level="DEBUG")
log = get_logger(__name__)


class MainWindow(QMainWindow, MainWindowHandlers, MainWindowUI):
    """Main application window: fullscreen map + overlay sidebar."""

    def __init__(self, server_url: str = "http://server:8000"):
        """Initialize main window."""
        super().__init__()
        
        log.info("navigation_mas_starting", server_url=server_url)
        
        self.server_url = server_url
        self.sidebar_visible = True
        self._zoom_slider_dragging = False
        
        # Bridges for JS-to-Python communication (signals/slots ONLY!)
        self.zoom_bridge = ZoomBridge()
        self.zoom_bridge.zoom_changed.connect(self._handle_zoom_from_js)
        
        self.points_bridge = PointsBridge()
        self.points_bridge.points_changed.connect(self._update_selected_points)
        
        # Points presenter: single source of truth for points with styling
        self.points_presenter = PointsPresenter()
        
        # Simulation state
        self.sim_agent_id = None
        self.sim_timer = None
        self.sim_fps = 30  # Default FPS from config
        
        # Start HTTP server for map.html assets (to avoid CORS)
        self._start_assets_httpd()
        
        # Setup window
        self.setWindowTitle("Navigation MAS — Fullscreen Map")
        self.setGeometry(0, 0, 1400, 900)
        self.showMaximized()
        
        # Setup UI
        self._setup_ui()
        
        # Setup keyboard shortcuts
        self._setup_shortcuts()
    
    def _start_assets_httpd(self) -> None:
        """Start HTTP server for map.html assets."""
        # ui/main_window.py -> ../assets
        assets_dir = os.path.join(
            os.path.dirname(__file__), '../assets'
        )
        handler = partial(SimpleHTTPRequestHandler, directory=assets_dir)
        httpd = ThreadingHTTPServer(("127.0.0.1", 9999), handler)
        self._assets_port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        print(f"DEBUG: Assets HTTP server started on port {self._assets_port}")
    
    def _setup_ui(self) -> None:
        """Setup user interface: fullscreen map + overlay sidebar."""
        central = QWidget()
        self.setCentralWidget(central)
        
        # Map frame (takes full window)
        self.map_frame = QWidget(central)
        self.map_frame.setGeometry(0, 0, self.width(), self.height())
        
        # === Map widget (fullscreen) ===
        self.map_widget = MapWidget(self.map_frame)
        self.map_widget.setGeometry(0, 0, self.width(), self.height())
        
        # Setup QWebChannel for JS-to-Python communication
        self.channel = QWebChannel()
        self.channel.registerObject('zoom_bridge', self.zoom_bridge)
        self.channel.registerObject('points_bridge', self.points_bridge)
        self.map_widget.page().setWebChannel(self.channel)
        
        # Load map HTML via HTTP server (to avoid CORS with tile server)
        map_url = f"http://127.0.0.1:{self._assets_port}/map.html"
        self.map_widget.load(QUrl(map_url))
        
        # Connect map loadFinished to inject TILE_URL
        self.map_widget.loadFinished.connect(self._on_map_loaded)
        
        # Setup sidebar (from MainWindowUI mixin)
        self._setup_sidebar()
        
        # Set parent_window for selected_points_widget
        if hasattr(self.sidebar, 'selected_points_widget'):
            self.sidebar.selected_points_widget.parent_window = self
        
        # Setup zoom controls (from MainWindowUI mixin)
        self._setup_zoom_controls()
    
    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts."""
        # ESC to quit
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        
        # Ctrl+1/2/3 for quick point setting at cursor
        QShortcut(QKeySequence("Ctrl+1"), self, activated=self._on_ctrl_1)
        QShortcut(QKeySequence("Ctrl+2"), self, activated=self._on_ctrl_2)
        QShortcut(QKeySequence("Ctrl+3"), self, activated=self._on_ctrl_3)
    
    def resizeEvent(self, event) -> None:
        """Handle window resize - update overlay positions."""
        super().resizeEvent(event)
        self._update_overlay_positions()
    
    def _update_overlay_positions(self) -> None:
        """Update positions of overlay widgets."""
        if not hasattr(self, 'map_frame'):
            return
        
        # Update map frame to fill window
        self.map_frame.setGeometry(0, 0, self.width(), self.height())
        self.map_widget.setGeometry(0, 0, self.width(), self.height())
        
        map_w = self.width()
        map_h = self.height()
        
        # Position sidebar at left with padding (~9px = 0.25cm)
        padding = 9
        if self.sidebar_visible:
            self.sidebar.move(padding, padding)
            self.sidebar.resize(self.sidebar.width(), map_h - 2 * padding)
            self.sidebar.show()
            # Hide toggle button when sidebar is visible
            self.toggle_btn.hide()
        else:
            self.sidebar.hide()
            # Show toggle button when sidebar is hidden
            self.toggle_btn.move(padding, padding)
            self.toggle_btn.show()
            self.toggle_btn.raise_()
        
        # Position zoom controls 4px from right edge
        if hasattr(self, 'zoom_container'):
            # Slider height = 1/3 screen height
            slider_height = map_h // 3
            self.zoom_slider.setFixedHeight(slider_height)
            
            # Container height = slider + buttons + spacing
            zoom_h = slider_height + 24 + 24 + 8  # 2 buttons + 2 gaps
            zoom_w = self.zoom_container.width()
            zoom_x = map_w - zoom_w - 4  # 4px from right edge
            zoom_y = max(20, (map_h - zoom_h) // 2)
            
            self.zoom_container.setFixedHeight(zoom_h)
            self.zoom_container.move(zoom_x, zoom_y)
            self.zoom_container.raise_()
    
    def _toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        self.sidebar_visible = not self.sidebar_visible
        self._update_overlay_positions()
    
    def _on_map_loaded(self, ok: bool) -> None:
        """Inject TILE_URL after map.html loads."""
        if not ok:
            print("ERROR: map.html failed to load")
            return
        
        # Inject TILE_URL from environment or use default
        tile_url = os.environ.get(
            "TILE_URL",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        )
        code = f"window.TILE_URL = '{tile_url}';"
        print(f"DEBUG: Injecting TILE_URL: {tile_url}")
        self.map_widget.page().runJavaScript(code)
        
        # Update overlay positions after map loads
        self._update_overlay_positions()
        
        # Flag to skip point synchronization after manual changes
        self._skip_points_sync_count = 0
        
        # Setup event-based updates instead of periodic polling
        # JS will call window.pointsChangedCallback() when points change
        self._setup_js_callbacks()
    
    def _setup_js_callbacks(self):
        """Setup JavaScript callbacks for event-based updates."""
        js_code = """
        // Setup points_bridge when QWebChannel is ready
        if (window.qt && window.qt.webChannelTransport) {
            new QWebChannel(window.qt.webChannelTransport, function(channel) {
                window.points_bridge = channel.objects.points_bridge;
                
                // Override the notification function to use the bridge
                window.pointsChangedCallback = function() {
                    console.log('Points changed, notifying Python via bridge');
                    if (window.points_bridge) {
                        window.points_bridge.notify_points_changed();
                    }
                };
                
                console.log('Points bridge connected');
            });
        }
        """
        self.map_widget.page().runJavaScript(js_code)
        log.debug("js_callbacks_setup")
    
    # All event handlers are now in MainWindowHandlers mixin
