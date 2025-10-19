"""Map widget with QWebEngineView and signals."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import pyqtSignal, QUrl, Qt
from PyQt5.QtGui import QFont


class WebConsolePage(QWebEnginePage):
    """Bridge JS console logs to Python output."""

    def javaScriptConsoleMessage(self, level: int, message: str,
                                 line_number: int, source_id: str):
        """Handle JavaScript console messages."""
        level_names = {0: 'LOG', 1: 'WARNING', 2: 'ERROR'}
        level_name = level_names.get(level, str(level))
        print(f"JS[{level_name}] {source_id}:{line_number} {message}")


class MapWidget(QWebEngineView):
    """Map widget using MapLibre GL JS."""

    zoom_changed = pyqtSignal(float)
    bounds_changed = pyqtSignal(tuple)
    map_moved = pyqtSignal(float, float)
    context_menu_requested = pyqtSignal(float, float)

    def __init__(self, parent: QWidget = None):
        """Initialize map widget."""
        super().__init__(parent)
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
        js_code = f"if (map) map.fitBounds([[{min_lon}, {min_lat}], [{max_lon}, {max_lat}]]);"
        self.execute_js(js_code)
