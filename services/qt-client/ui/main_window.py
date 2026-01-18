"""Main application window with fullscreen map + overlay sidebar."""
import os
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

from PyQt5.QtWidgets import QMainWindow, QWidget, QShortcut
from PyQt5.QtCore import QUrl
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtGui import QKeySequence

from ui.widgets.map_widget import MapWidget
from handlers.zoom_bridge import ZoomBridge
from handlers.points_bridge import PointsBridge
from handlers.logger_bridge import LoggerBridge
from handlers.config_bridge import ConfigBridge
from models.points_presenter import PointsPresenter
from ui.main_window_handlers import MainWindowHandlers
from ui.main_window_ui import MainWindowUI
from services.common.config import config_loader
from loguru import logger as log

# Logging is configured in loguru_config.py on import
# No need to call configure_loguru() here


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
        # DISABLED: Causes "js: Uncaught SyntaxError" during zoom
        # TODO: Find alternative approach for zoom sync
        # self.zoom_bridge.zoom_changed.connect(self._handle_zoom_from_js)
        
        self.points_bridge = PointsBridge()
        self.points_bridge.points_changed.connect(self._update_selected_points)
        
        self.logger_bridge = LoggerBridge()
        # No connection needed - LoggerBridge logs directly
        
        # Config bridge - exposes GUI config to JS
        gui_config = config_loader.load('client/gui.yaml')
        
        # Inject server_url into config for JS (so it knows where to connect)
        gui_config['apiBaseUrl'] = self.server_url
        
        self.config_bridge = ConfigBridge(gui_config)
        debug_enabled = gui_config.get('debug', {}).get('enabled', False)
        log.info(f"gui_config_loaded debug_enabled={debug_enabled} apiBaseUrl={self.server_url}")
        
        # Points presenter: single source of truth for points with styling
        self.points_presenter = PointsPresenter()
        
        # Simulation state
        self.sim_agent_id = None
        self.sim_timer = None
        self.sim_fps = 30  # Default FPS from config
        
        # Start HTTP server for map.html assets (to avoid CORS)
        self._start_assets_httpd()
        
        # Setup window
        self.setWindowTitle(self.tr("Navigation MAS — Fullscreen Map"))
        self.setGeometry(0, 0, 1400, 900)
        # Setup translation
        self._setup_translation()
        
        # Setup UI
        self._setup_ui()
        
        # Setup keyboard shortcuts
        self._setup_shortcuts()
        
        self.showMaximized()
    
    def _setup_translation(self):
        """Load translations based on config."""
        from PyQt5.QtCore import QTranslator, QLocale
        from PyQt5.QtWidgets import QApplication
        
        # Get language from config (default to system)
        # Get language from config (default to system)
        lang = "en"  # Default
        try:
            from services.common.config import config_loader
            c = config_loader.load('client/gui.yaml')
            lang = c.get('language', 'en')
        except Exception as e:
            log.warning(f"Failed to load gui config for translation: {e}")
            
        log.info(f"Loading translation for language: {lang}")
        
        self.translator = QTranslator()
        # Assume translations are in 'translations' dir relative to qt-client root
        # We can find qt-client root relative to this file: ui/../translations
        base_dir = os.path.dirname(os.path.dirname(__file__))
        qm_path = os.path.join(base_dir, 'translations', f'app_{lang}.qm')
        
        if os.path.exists(qm_path):
            if self.translator.load(qm_path):
                QApplication.instance().installTranslator(self.translator)
                log.info(f"Loaded translation file: {qm_path}")
            else:
                log.error(f"Failed to load translation file: {qm_path}")
        else:
             log.warning(f"Translation file not found: {qm_path} (Using default/English)")
    
    def _start_assets_httpd(self) -> None:
        """Start HTTP server for map.html assets."""
        assets_dir = os.path.join(
            os.path.dirname(__file__), '../assets'
        )
        from functools import partial
        handler = partial(SimpleHTTPRequestHandler, directory=assets_dir)
        httpd = ThreadingHTTPServer(("127.0.0.1", 9999), handler)
        self._assets_port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        log.debug("assets_httpd_started", port=self._assets_port)
    
    def _setup_ui(self) -> None:
        """Setup user interface: fullscreen map + overlay sidebar."""
        central = QWidget()
        self.setCentralWidget(central)
        
        # Map frame (takes full window)
        self.map_frame = QWidget(central)
        self.map_frame.setGeometry(0, 0, self.width(), self.height())
        
        # === Map widget (fullscreen) ===
        # NOTE: MapWidget constructor sets up WebConsolePage internally
        self.map_widget = MapWidget(self.map_frame)
        self.map_widget.setGeometry(0, 0, self.width(), self.height())
        
        # CRITICAL: Clear WebView HTTP cache to force reload fresh JS
        self.map_widget.page().profile().clearHttpCache()
        log.info("webview_cache_cleared")
        
        # Setup QWebChannel for JS-to-Python communication
        self.channel = QWebChannel()
        self.channel.registerObject('zoom_bridge', self.zoom_bridge)
        self.channel.registerObject('points_bridge', self.points_bridge)
        self.channel.registerObject('logger_bridge', self.logger_bridge)
        self.channel.registerObject('config_bridge', self.config_bridge)
        self.map_widget.page().setWebChannel(self.channel)
        
        # Connect map loadFinished signal (URLs already in HTML)
        self.map_widget.loadFinished.connect(self._on_map_loaded)
        
        # Load map HTML via HTTP server
        map_url = f"http://127.0.0.1:{self._assets_port}/map.html"
        log.debug("loading_map_html", url=map_url)
        self.map_widget.load(QUrl(map_url))
        
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
        """Handle map.html load completion."""
        log.info("map_loaded_signal", success=ok)
        
        if not ok:
            log.error("map_html_load_failed")
            return
        
        log.debug("map_ready")
        
        # Update overlay positions after map loads
        self._update_overlay_positions()
        
        # Flag to skip point synchronization after manual changes
        self._skip_points_sync_count = 0
        
        # Setup event-based updates instead of periodic polling
        # JS will call window.pointsChangedCallback() when points change
        self._setup_js_callbacks()
        
        # MVT tiles auto-load via vectorTileUrl, no need for manual fetch
        # self._auto_load_graph()
    
    def _auto_load_graph(self) -> None:
        """Automatically load graph from server on startup."""
        from config import DataConfig
        from services.api_workers import GraphFetchWorker
        
        log.info("auto_loading_graph")
        
        # Use moscow_small bbox from config
        bbox = DataConfig.DEFAULT_TEST_BBOX
        
        # Create background worker
        self._graph_worker = GraphFetchWorker(self.server_url, bbox)
        self._graph_worker.finished.connect(self._on_auto_graph_loaded)
        self._graph_worker.error.connect(
            lambda err: log.error("auto_graph_load_failed", error=err)
        )
        self._graph_worker.start()
    
    def _on_auto_graph_loaded(self, data: dict) -> None:
        """Handle auto-loaded graph."""
        import json
        
        geojson = data['geojson']
        log.info(
            "auto_graph_loaded",
            ways=data['total_ways'],
            cached=data.get('cached'),
            features=len(geojson.get('features', []))
        )
        
        # Display on map using 'graph' GeoJSON source (not MVT!)
        geojson_str = json.dumps(geojson)
        js_code = f"""
        if (window.app && window.app.setGraphGeoJSON) {{
            window.app.setGraphGeoJSON({geojson_str});
            if (window.app.fitToGraph) {{
                window.app.fitToGraph();
            }}
        }}
        """
        self.map_widget.page().runJavaScript(js_code)
    
    def _setup_js_callbacks(self):
        """Setup JavaScript callbacks for event-based updates.
        
        IMPORTANT: WebChannel is already initialized in map-main.js!
        Don't create another QWebChannel instance - just wait for it.
        """
        js_code = """
        // Wait for existing QWebChannel to initialize (from map-main.js)
        // Don't create new QWebChannel - reuse the existing one
        function waitForChannel(attempts = 0) {
            // Check if QWebChannel transport is available
            if (!window.qt || !window.qt.webChannelTransport) {
                if (attempts < 100) {
                    // Wait for Qt transport (setWebChannel() from Python)
                    setTimeout(() => waitForChannel(attempts + 1), 50);
                } else {
                    console.error('Timeout: Qt WebChannel transport not available');
                }
                return;
            }
            
            // Transport is ready, check if map-main.js initialized the channel
            const hasChannel = window.globalChannel;
            if (hasChannel) {
                // Channel already initialized in map-main.js
                const bridge = window.globalChannel.objects.points_bridge;
                window.points_bridge = bridge;
                
                // Override the notification function to use the bridge
                window.pointsChangedCallback = function() {
                    console.log('Points changed, notifying Python via bridge');
                    if (window.points_bridge) {
                        window.points_bridge.notify_points_changed();
                    }
                };
                
                console.log('Points bridge connected to existing channel');
            } else if (attempts < 100) {
                // Wait for map-main.js to initialize channel (after qwebchannel.js loads)
                setTimeout(() => waitForChannel(attempts + 1), 50);
            } else {
                console.error('Timeout: global WebChannel not initialized by map-main.js');
            }
        }
        
        waitForChannel();
        """
        self.map_widget.page().runJavaScript(js_code)
        log.debug("js_callbacks_setup")
    
    # All event handlers are now in MainWindowHandlers mixin
