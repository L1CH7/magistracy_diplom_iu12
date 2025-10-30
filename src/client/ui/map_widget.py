from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import pyqtSignal, QUrl

class MapWidget(QWebEngineView):
    """
    MapWidget — отдельный виджет карты, наследует QWebEngineView.
    Сигналы: zoom_changed, context_menu_at
    Методы: load(), getZoom(), setZoom(), executeJS()
    """
    zoom_changed = pyqtSignal(float)
    context_menu_at = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_zoom = 12.0
        self._tile_url = None

    def load_map(self, url: str):
        self.load(QUrl(url))

    def get_zoom(self):
        return self._current_zoom

    def set_zoom(self, zoom: float):
        self._current_zoom = zoom
        self.page().runJavaScript(f"window.map && window.map.setZoom({zoom});")

    def execute_js(self, code: str):
        self.page().runJavaScript(code)

    # TODO: Подключить обработку событий JS → Python (zoom, context menu)
