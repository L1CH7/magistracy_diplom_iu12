"""Map widget with QWebEngineView and signals."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import pyqtSignal, QUrl, Qt
from PyQt5.QtGui import QFont
from loguru import logger as log


class WebConsolePage(QWebEnginePage):
    """Bridge JS console logs to Python output with error interception."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.loadFinished.connect(self._inject_error_handler)

    def _inject_error_handler(self):
        """Inject global JS error handler to catch all errors."""
        self.runJavaScript("""
            (function() {
                window.addEventListener('error', function(e) {
                    console.error('[GLOBAL ERROR]', {
                        message: e.message,
                        filename: e.filename,
                        lineno: e.lineno,
                        colno: e.colno,
                        stack: e.error ? e.error.stack : 'no stack'
                    });
                }, true);
                
                const originalEval = window.eval;
                window.eval = function(code) {
                    try {
                        return originalEval(code);
                    } catch(e) {
                        const preview = code.substring(0, 80);
                        console.error('[EVAL ERROR]', e.message, preview);
                        throw e;
                    }
                };
            })();
        """)

    def javaScriptConsoleMessage(self, level: int, message: str,
                                 line_number: int, source_id: str):
        """Handle JavaScript console messages."""
        # Map JS console levels to loguru (loguru style output)
        source_file = source_id.split('/')[-1] if source_id else "unknown"
        
        if level == 0:  # LOG/INFO
            log.info(f"[JS] {message}")
        elif level == 1:  # WARNING
            log.warning(f"[JS] {message}")
        else:  # ERROR
            log.error(f"[JS] {message} (line {line_number} in {source_file})")


class MapWidget(QWebEngineView):
    """Map widget using MapLibre GL JS."""

    zoom_changed = pyqtSignal(float)
    bounds_changed = pyqtSignal(tuple)
    map_moved = pyqtSignal(float, float)
    context_menu_requested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget = None):
        """Initialize map widget."""
        super().__init__(parent)
        
        # Setup custom page with console logging
        self.setPage(WebConsolePage())
        
        self.setContextMenuPolicy(Qt.NoContextMenu)

    def load_map(self, html_file: str) -> None:
        """Load map HTML file."""
        file_url = QUrl.fromLocalFile(html_file)
        self.load(file_url)

    def execute_js(self, code: str) -> None:
        """Execute JavaScript in map."""
        self.page().runJavaScript(code)

    def set_zoom(self, zoom: float) -> None:
        """Set map zoom level."""
        zoom = max(0.0, min(24.0, zoom))
        js_code = f"if (map) map.easeTo({{zoom: {zoom}}});"
        self.execute_js(js_code)

    def fit_bounds(self, min_lon: float, min_lat: float,
                   max_lon: float, max_lat: float) -> None:
        """Fit map to bounds."""
        js_code = (
            f"if (map) map.fitBounds("
            f"[[{min_lon}, {min_lat}], [{max_lon}, {max_lat}]]);"
        )
        self.execute_js(js_code)
