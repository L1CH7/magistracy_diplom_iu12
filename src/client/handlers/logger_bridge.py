"""Logger bridge for JS-to-Python logging via QWebChannel."""
from PyQt5.QtCore import QObject, pyqtSlot
from loguru import logger as log


class LoggerBridge(QObject):
    """Bridge for logging from JavaScript."""

    @pyqtSlot(str)
    def log_info(self, message: str):
        """Log info message from JS."""
        log.info(f"[JS] {message}")

    @pyqtSlot(str)
    def log_debug(self, message: str):
        """Log debug message from JS."""
        log.debug(f"[JS] {message}")

    @pyqtSlot(str)
    def log_warning(self, message: str):
        """Log warning message from JS."""
        log.warning(f"[JS] {message}")

    @pyqtSlot(str)
    def log_error(self, message: str):
        """Log error message from JS."""
        log.error(f"[JS] {message}")

    @pyqtSlot(str)
    def log_trace(self, message: str):
        """Log trace message from JS."""
        log.trace(f"[JS] {message}")
