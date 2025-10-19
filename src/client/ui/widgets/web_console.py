"""Web engine page with JavaScript console logging."""
from PyQt5.QtWebEngineWidgets import QWebEnginePage


class WebConsolePage(QWebEnginePage):
    """Bridge JS console logs to Python stdout."""

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        try:
            lvl = int(level)
        except Exception:
            lvl = level
        print(f"JS[{lvl}] {sourceID}:{lineNumber} {message}")
