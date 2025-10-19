"""Collapsible section widget for organizing UI panels."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton


class CollapsibleSection(QWidget):
    """Custom collapsible section for logs (Route, Status, Speed)."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._open = False
        self._title = title
        self._content = QWidget()
        self._content.setVisible(self._open)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        self._header_btn = QPushButton(self._header_text(self._title))
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(self._open)
        self._header_btn.clicked.connect(self._toggle)
        self._header_btn.setStyleSheet(
            "text-align: left; font-weight: bold; padding: 6px; "
            "border-radius: 4px; background-color: #e5e7eb; "
            "border: 1px solid #d1d5db;"
        )
        self._layout.addWidget(self._header_btn)
        self._layout.addWidget(self._content)

    def _header_text(self, title: str) -> str:
        return ("▼ " if self._open else "▶ ") + title

    def _toggle(self) -> None:
        self._open = not self._open
        self._content.setVisible(self._open)
        self._header_btn.setText(self._header_text(self._title))
        self._header_btn.setChecked(self._open)

    def add_widget(self, w: QWidget) -> None:
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.addWidget(w)
