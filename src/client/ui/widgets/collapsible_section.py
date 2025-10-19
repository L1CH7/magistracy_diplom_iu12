"""Collapsible section widget for expandable panels."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton
from PyQt5.QtCore import Qt


class CollapsibleSection(QWidget):
    """Collapsible section with header and content area.
    
    Features:
    - Click header to toggle visibility
    - Arrow indicator (▼/▶)
    - Automatic layout management
    - Can be extended with add_widget()
    """

    def __init__(self, title: str, parent: QWidget = None):
        """Initialize collapsible section.
        
        Args:
            title: Section title
            parent: Parent widget
        """
        super().__init__(parent)
        self._open = False
        self._title = title
        self._content = QWidget()
        self._content.setVisible(self._open)

        # Main layout
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        # Header button
        self._header_btn = QPushButton(self._header_text(self._title))
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(self._open)
        self._header_btn.clicked.connect(self._toggle)
        self._header_btn.setCursor(Qt.PointingHandCursor)
        self._header_btn.setStyleSheet(
            "text-align: left; font-weight: bold; padding: 6px; "
            "border-radius: 4px; background-color: #e5e7eb; "
            "border: 1px solid #d1d5db;"
        )
        self._layout.addWidget(self._header_btn)

        # Content area
        self._layout.addWidget(self._content)

    def _header_text(self, title: str) -> str:
        """Get header text with arrow indicator."""
        arrow = "▼ " if self._open else "▶ "
        return arrow + title

    def _toggle(self) -> None:
        """Toggle section visibility."""
        self._open = not self._open
        self._content.setVisible(self._open)
        self._header_btn.setText(self._header_text(self._title))
        self._header_btn.setChecked(self._open)

    def add_widget(self, widget: QWidget) -> None:
        """Add widget to content area.
        
        Args:
            widget: Widget to add
        """
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.addWidget(widget)

    def set_open(self, open_state: bool) -> None:
        """Set section open/closed state.
        
        Args:
            open_state: True to open, False to close
        """
        if self._open != open_state:
            self._toggle()

    def is_open(self) -> bool:
        """Check if section is open."""
        return self._open
