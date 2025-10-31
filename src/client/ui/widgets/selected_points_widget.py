from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea
)
from PyQt5.QtCore import Qt
from src.utils.logging_config import get_logger

log = get_logger(__name__)


class SelectedPointsWidget(QFrame):
    """Sandwich-style list of selected points (From, Via, To)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setStyleSheet(
            "QFrame { background-color: #f9fafb; "
            "border-radius: 6px; border: 1px solid #e5e7eb; }"
        )
        self.setMaximumHeight(250)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll area for points
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; }"
        )
        
        # Container for sandwich tiles
        self.container = QFrame()
        self.container.setStyleSheet(
            "QFrame { background-color: #ffffff; "
            "border: 1px solid #d1d5db; border-radius: 6px; "
            "margin: 6px; padding: 0px; }"
        )
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)
        
        self.scroll.setWidget(self.container)
        main_layout.addWidget(self.scroll)
        
        self.points = []

    def update_points(self, points):
        """Update displayed points list with sandwich tiles."""
        log.debug(
            "widget_update_points_CALLED",
            incoming_count=len(points),
            current_count=len(self.points),
            points_data=[
                f"{p.get('lon', 0):.2f},{p.get('lat', 0):.2f}"
                for p in points
            ]
        )
        
        self.points = points
        self._rebuild_list()
    
    def _rebuild_list(self) -> None:
        """Rebuild sandwich list from current self.points."""
        # Полностью очищаем layout
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Если нет точек - показываем placeholder
        if not self.points:
            label = QLabel("No points selected\n(Ctrl+1/2/3 to add)")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "color: #9ca3af; font-style: italic; padding: 20px;"
            )
            self.container_layout.addWidget(label)
            return
        
        # Создаем sandwich tiles
        n = len(self.points)
        for idx in range(n):
            point = self.points[idx]
            is_first = (idx == 0)
            is_last = (idx == n - 1)
            
            tile = self._create_sandwich_tile(
                idx, point, is_first, is_last
            )
            self.container_layout.addWidget(tile)

    def _create_sandwich_tile(
        self, idx: int, point: dict, is_first: bool, is_last: bool
    ) -> QFrame:
        """Create a tile for one point in the sandwich."""
        tile = QFrame()
        
        # Styling - only bottom border between tiles
        border_style = (
            "border-bottom: 1px solid #e5e7eb;" if idx < len(self.points) - 1
            else "border-bottom: none;"
        )
        tile.setStyleSheet(
            f"QFrame {{ background-color: #ffffff; border: none; "
            f"{border_style} padding: 0px; margin: 0px; }}"
        )
        tile.setMaximumHeight(32)
        tile.setMinimumHeight(32)
        
        layout = QHBoxLayout(tile)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        
        # 1. Marker circle matching map display
        dot = QFrame()
        
        if is_first:
            # From: white circle with blue border
            dot.setMinimumSize(14, 14)
            dot.setMaximumSize(14, 14)
            dot.setStyleSheet(
                "QFrame { background-color: #ffffff; "
                "border: 2px solid #2563eb; border-radius: 7px; }"
            )
        elif is_last:
            # To: white circle with red border
            dot.setMinimumSize(14, 14)
            dot.setMaximumSize(14, 14)
            dot.setStyleSheet(
                "QFrame { background-color: #ffffff; "
                "border: 2px solid #dc2626; border-radius: 7px; }"
            )
        else:
            # Via: use display_color from presenter
            color = point.get('display_color', '#8b5cf6')
            dot.setMinimumSize(12, 12)
            dot.setMaximumSize(12, 12)
            dot.setStyleSheet(
                f"QFrame {{ background-color: {color}; "
                f"border: 2px solid #000000; border-radius: 6px; }}"
            )
        
        layout.addWidget(dot)
        
        # 2. Point type label
        if is_first:
            type_label = QLabel("From")
        elif is_last:
            type_label = QLabel("To")
        else:
            type_label = QLabel("Via")
        
        type_label.setStyleSheet(
            "font-size: 11px; color: #374151; min-width: 24px;"
        )
        layout.addWidget(type_label)
        
        # 3. Coordinates (compact)
        lon = point.get('lon', 0)
        lat = point.get('lat', 0)
        coord_text = f"{lon:.2f}, {lat:.2f}"
        coord_label = QLabel(coord_text)
        coord_label.setStyleSheet(
            "font-family: monospace; font-size: 10px; color: #6b7280;"
        )
        layout.addWidget(coord_label, 1)
        
        # 4. Up button (not for first)
        if idx > 0:
            up_btn = QPushButton("▲")
            up_btn.setMinimumSize(20, 20)
            up_btn.setMaximumSize(20, 20)
            up_btn.setStyleSheet(
                "QPushButton { background-color: transparent; "
                "border: none; padding: 0px; "
                "color: #9ca3af; font-size: 9px; font-weight: bold; } "
                "QPushButton:hover { color: #6b7280; }"
            )
            up_btn.clicked.connect(lambda: self._move_point(idx, -1))
            layout.addWidget(up_btn)
        
        # 5. Down button (not for last)
        if idx < len(self.points) - 1:
            down_btn = QPushButton("▼")
            down_btn.setMinimumSize(20, 20)
            down_btn.setMaximumSize(20, 20)
            down_btn.setStyleSheet(
                "QPushButton { background-color: transparent; "
                "border: none; padding: 0px; "
                "color: #9ca3af; font-size: 9px; font-weight: bold; } "
                "QPushButton:hover { color: #6b7280; }"
            )
            down_btn.clicked.connect(lambda: self._move_point(idx, 1))
            layout.addWidget(down_btn)
        
        # 6. Delete button
        del_btn = QPushButton("✕")
        del_btn.setMinimumSize(20, 20)
        del_btn.setMaximumSize(20, 20)
        del_btn.setStyleSheet(
            "QPushButton { background-color: transparent; "
            "border: none; padding: 0px; "
            "color: #ef4444; font-size: 10px; font-weight: bold; } "
            "QPushButton:hover { color: #dc2626; }"
        )
        del_btn.clicked.connect(lambda: self._remove_point(idx))
        layout.addWidget(del_btn)
        
        return tile

    def _move_point(self, from_idx: int, direction: int) -> None:
        """Move a point up (-1) or down (+1) in the list."""
        if not self.parent_window:
            log.error("widget_move_point_NO_PARENT")
            return
        
        log.info(
            "widget_move_point_START",
            from_idx=from_idx,
            direction=direction,
            points_before=len(self.points)
        )
        
        to_idx = from_idx + direction
        
        # Use presenter to move point
        presenter = self.parent_window.points_presenter
        if presenter.move_point(from_idx, to_idx):
            log.info(
                "widget_move_point_SWAPPED",
                from_idx=from_idx,
                to_idx=to_idx
            )
            
            # Set flag to skip next sync from JS
            self.parent_window._skip_points_sync_count = 3
            log.debug("widget_set_skip_flag", count=3)
            
            # Update both widgets with new styled points
            self._refresh_from_presenter()
            
            log.info(
                "widget_move_point_COMPLETE",
                final_count=presenter.count()
            )
        else:
            log.error(
                "widget_move_point_FAILED",
                from_idx=from_idx,
                to_idx=to_idx
            )

    def _remove_point(self, idx: int) -> None:
        """Remove a point from the list."""
        if not self.parent_window:
            log.error("widget_remove_point_NO_PARENT")
            return
        
        log.info(
            "widget_remove_point_START",
            idx=idx,
            points_before=len(self.points)
        )
        
        # Use presenter to remove point
        presenter = self.parent_window.points_presenter
        if presenter.remove_point(idx):
            log.info("widget_remove_point_REMOVED", idx=idx)
            
            # Set flag to skip next sync from JS
            self.parent_window._skip_points_sync_count = 3
            log.debug("widget_set_skip_flag", count=3)
            
            # Update both widgets with new styled points
            self._refresh_from_presenter()
            
            log.info(
                "widget_remove_point_COMPLETE",
                final_count=presenter.count()
            )
        else:
            log.error("widget_remove_point_FAILED", idx=idx)
    
    def _refresh_from_presenter(self) -> None:
        """Refresh sandwich and map from presenter's styled points."""
        if not self.parent_window:
            log.error("refresh_from_presenter_NO_PARENT")
            return
        
        presenter = self.parent_window.points_presenter
        styled = presenter.get_styled_points()
        
        log.info(
            "refresh_from_presenter_START",
            count=len(styled),
            display_colors=[
                p.get('display_color', 'N/A') for p in styled
            ],
            display_types=[
                p.get('display_type', 'N/A') for p in styled
            ]
        )
        
        # Update sandwich display
        self.points = styled
        self._rebuild_list()
        
        # Update map markers via JS
        self._update_map_points()
        
        log.debug("refresh_from_presenter_DONE", count=presenter.count())

    def _update_map_points(self) -> None:
        """Update map markers after reordering or deletion."""
        log.debug(
            "widget_update_map_START",
            points_count=len(self.points)
        )
        
        if not self.parent_window:
            log.warning("widget_update_map_NO_PARENT")
            return
        
        # Get map widget
        map_widget = getattr(self.parent_window, 'map_widget', None)
        if not map_widget:
            log.warning("widget_update_map_NO_MAP_WIDGET")
            return
        
        # Convert points to JSON and set in JS
        import json
        points_json = json.dumps(self.points)
        
        log.info(
            "widget_update_map_SENDING_TO_JS",
            points_count=len(self.points),
            json_length=len(points_json),
            display_colors=[
                p.get('display_color', 'N/A') for p in self.points
            ],
            first_point_keys=list(self.points[0].keys()) if self.points else []
        )
        
        # Use setAllPoints to replace entire array in JS
        code = f"window.app && window.app.setAllPoints({points_json});"
        map_widget.page().runJavaScript(code)
        
        log.debug("widget_update_map_COMPLETE")
