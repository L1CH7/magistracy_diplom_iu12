"""Point management - handling adding, removing, and updating navigation points."""
from typing import List, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

try:
    from ..models import NavigationState
except ImportError:
    from models import NavigationState


class PointHandler(QObject):
    """Manages navigation points (from, to, via) on the map."""
    
    # Signals for point changes
    points_updated = pyqtSignal(list)  # Emitted when points array changes
    markers_updated = pyqtSignal()     # Emitted when map markers need update
    
    def __init__(self, gui_instance, nav_state: NavigationState):
        super().__init__()
        self.gui = gui_instance
        self.nav_state = nav_state
        
        # Local points array (may sync with nav_state later)
        self.points: List[Dict] = []
        self._color_idx = 0
        
        # Color palette for via points
        self.color_palette = [
            "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
            "#ec4899", "#a855f7", "#0ea5e9", "#10b981"
        ]
        
        # Connect signals
        self.nav_state.point_added.connect(self._on_point_added)
        self.nav_state.point_removed.connect(self._on_point_removed)
        self.nav_state.points_cleared.connect(self._on_points_cleared)
    
    def set_point(self, point_type: str, lon: float, lat: float) -> None:
        """Set a navigation point (from, to, or via)."""
        if point_type == "from":
            self._set_from_point(lon, lat)
        elif point_type == "to":
            self._set_to_point(lon, lat)
        elif point_type == "via":
            self._set_via_point(lon, lat)
        else:
            self.nav_state.error_occurred.emit(
                f"Invalid point type: {point_type}"
            )
    
    def _set_from_point(self, lon: float, lat: float) -> None:
        """Set the starting point."""
        color = self.color_palette[
            self._color_idx % len(self.color_palette)
        ]
        self._color_idx += 1
        
        if not self.points:
            self.points.append({
                "lon": lon, "lat": lat, "color": color, "type": "from"
            })
        else:
            self.points[0] = {
                "lon": lon, "lat": lat, "color": color, "type": "from"
            }
        
        # Update UI fields
        self.gui.start_lat.setText(f"{lat:.6f}")
        self.gui.start_lon.setText(f"{lon:.6f}")
        
        # Update map
        self._update_map_markers()
        self._update_points_list()
        
        # Emit signal
        self.points_updated.emit(self.points)
    
    def _set_to_point(self, lon: float, lat: float) -> None:
        """Set the ending point."""
        color = self.color_palette[
            self._color_idx % len(self.color_palette)
        ]
        self._color_idx += 1
        
        if len(self.points) == 0:
            self.points.append({
                "lon": lon, "lat": lat, "color": color, "type": "to"
            })
        elif len(self.points) == 1:
            self.points.append({
                "lon": lon, "lat": lat, "color": color, "type": "to"
            })
        else:
            # Replace last
            self.points[-1] = {
                "lon": lon, "lat": lat, "color": color, "type": "to"
            }
        
        # Update UI fields
        self.gui.end_lat.setText(f"{lat:.6f}")
        self.gui.end_lon.setText(f"{lon:.6f}")
        
        # Update map
        self._update_map_markers()
        self._update_points_list()
        
        # Emit signal
        self.points_updated.emit(self.points)
    
    def _set_via_point(self, lon: float, lat: float) -> None:
        """Add a via point (waypoint)."""
        if len(self.points) < 2:
            # Not enough points for via yet
            return
        
        color = self.color_palette[
            self._color_idx % len(self.color_palette)
        ]
        self._color_idx += 1
        
        # Insert before the last point (which is "to")
        self.points.insert(-1, {
            "lon": lon, "lat": lat, "color": color, "type": "via"
        })
        
        # Update map
        self._update_map_markers()
        self._update_points_list()
        
        # Emit signal
        self.points_updated.emit(self.points)
    
    def remove_point(self, idx: int) -> None:
        """Remove a point at specific index."""
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            
            # Update from/to fields if needed
            if len(self.points) == 0:
                self.gui.start_lat.setText("55.751244")
                self.gui.start_lon.setText("37.618423")
                self.gui.end_lat.setText("55.755826")
                self.gui.end_lon.setText("37.617300")
            elif len(self.points) == 1:
                p = self.points[0]
                self.gui.start_lat.setText(f"{p['lat']:.6f}")
                self.gui.start_lon.setText(f"{p['lon']:.6f}")
                self.gui.end_lat.setText("55.755826")
                self.gui.end_lon.setText("37.617300")
            else:
                p0 = self.points[0]
                p1 = self.points[-1]
                self.gui.start_lat.setText(f"{p0['lat']:.6f}")
                self.gui.start_lon.setText(f"{p0['lon']:.6f}")
                self.gui.end_lat.setText(f"{p1['lat']:.6f}")
                self.gui.end_lon.setText(f"{p1['lon']:.6f}")
            
            # Update map
            self._update_map_markers()
            self._update_points_list()
            
            # Emit signal
            self.points_updated.emit(self.points)
    
    def clear_all(self) -> None:
        """Clear all navigation points."""
        self.points = []
        self.gui.start_lat.setText("55.751244")
        self.gui.start_lon.setText("37.618423")
        self.gui.end_lat.setText("55.755826")
        self.gui.end_lon.setText("37.617300")
        self.gui._js("window.app && window.app.clearAllMarkers();")
        self._update_points_list()
        self.points_updated.emit(self.points)
    
    def _update_map_markers(self) -> None:
        """Clear all markers and add current points."""
        self.gui._js("window.app && window.app.clearAllMarkers();")
        
        if not self.points:
            return
        
        # Add markers for each point
        for idx, point in enumerate(self.points):
            lon = point["lon"]
            lat = point["lat"]
            
            if idx == 0:
                # From - blue
                marker_color = "#2563eb"
            elif idx == len(self.points) - 1:
                # To - red
                marker_color = "#dc2626"
            else:
                # Via - its own color
                marker_color = point["color"]
            
            code = (
                f"window.app && "
                f"window.app.addMarker({{"
                f"lon: {lon}, lat: {lat}"
                f"}}, '{marker_color}');"
            )
            self.gui._js(code)
        
        self.markers_updated.emit()
    
    def _update_points_list(self) -> None:
        """Update the points list widget in sidebar."""
        # TODO: Implement points list widget update
        # This will update self.gui.points_list_widget
        pass
    
    @pyqtSlot()
    def _on_point_added(self, point) -> None:
        """Handle point added signal from nav_state."""
        # TODO: Sync with nav_state.points
        pass
    
    @pyqtSlot(int)
    def _on_point_removed(self, idx: int) -> None:
        """Handle point removed signal from nav_state."""
        # TODO: Sync with nav_state.points
        pass
    
    @pyqtSlot()
    def _on_points_cleared(self) -> None:
        """Handle points cleared signal from nav_state."""
        # TODO: Sync with nav_state.points
        pass
    
    def get_points(self) -> List[Dict]:
        """Get current points array."""
        return self.points.copy()
