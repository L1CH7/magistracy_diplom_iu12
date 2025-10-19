"""Navigation state manager - Single Source of Truth.

This is the central model that holds all application state.
It emits signals when state changes, allowing UI to react
independently without direct coupling.

Signals allow:
- Loose coupling (UI doesn't know about state implementation)
- Async updates (state can update without waiting for UI)
- Testing (can mock signals and check which were emitted)
- Performance (Qt handles signal delivery efficiently)
"""
from typing import List, Optional, Tuple
from PyQt5.QtCore import QObject, pyqtSignal

from .point import Point
from .route import Route


class NavigationState(QObject):
    """Central state manager - Model for entire application.
    
    All state changes go through this object, which emits signals
    when state changes. This ensures:
    
    1. Single source of truth (no state duplication)
    2. Loose coupling (components don't need direct references)
    3. Reactive updates (signal-driven architecture)
    4. Thread-safe updates (Qt handles signal delivery)
    """
    
    # ============ POINT MANAGEMENT SIGNALS ============
    point_added = pyqtSignal(Point)          # New point added
    point_removed = pyqtSignal(int)          # Point removed by index
    points_cleared = pyqtSignal()            # All points cleared
    # All points changed (list of Points)
    points_changed = pyqtSignal(list)
    
    # ============ ROUTE MANAGEMENT SIGNALS ============
    route_updated = pyqtSignal(Route)        # New route calculated
    route_cleared = pyqtSignal()             # Route cleared
    
    # ============ MAP STATE SIGNALS ============
    zoom_changed = pyqtSignal(float)         # Zoom level changed
    # Bounds changed (minLon, minLat, maxLon, maxLat)
    bounds_changed = pyqtSignal(tuple)
    # Map center moved (lon, lat)
    map_center_moved = pyqtSignal(float, float)
    # Map clicked (lon, lat)
    map_clicked = pyqtSignal(float, float)
    
    # ============ STATUS/ERROR SIGNALS ============
    error_occurred = pyqtSignal(str)         # Error message
    status_changed = pyqtSignal(str)         # Status for display
    # Operation started (e.g., "Loading graph...")
    operation_started = pyqtSignal(str)
    operation_completed = pyqtSignal()       # Operation completed
    
    def __init__(self):
        """Initialize state manager."""
        super().__init__()
        
        # Point management
        self._points: List[Point] = []
        
        # Route management
        self._route: Optional[Route] = None
        
        # Map state
        self._current_zoom: float = 13.0
        self._current_bounds: Optional[Tuple] = None
        self._map_center: Tuple[float, float] = (37.6, 55.75)  # Moscow center
        self.tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        
        # Status
        self._current_status: str = "Ready"
    
    # ============ POINT MANAGEMENT ============
    
    def add_point(self, point_type: str, lon: float, lat: float) -> None:
        """Add navigation point.
        
        Args:
            point_type: 'start', 'end', or 'via'
            lon: Longitude
            lat: Latitude
        """
        if not self._is_valid_point_type(point_type):
            self.error_occurred.emit(f"Invalid point type: {point_type}")
            return
        
        point = Point(point_type=point_type, lon=lon, lat=lat)
        self._points.append(point)
        
        self.point_added.emit(point)
        self.points_changed.emit(self._points.copy())
    
    def remove_point(self, index: int) -> None:
        """Remove point by index.
        
        Args:
            index: Point index
        """
        if not (0 <= index < len(self._points)):
            self.error_occurred.emit(f"Invalid point index: {index}")
            return
        
        self._points.pop(index)
        self.point_removed.emit(index)
        self.points_changed.emit(self._points.copy())
    
    def clear_points(self) -> None:
        """Clear all points."""
        self._points.clear()
        self.points_cleared.emit()
        self.points_changed.emit(self._points.copy())
    
    def get_points(self) -> List[Point]:
        """Get copy of all points.
        
        Returns:
            List of Point objects
        """
        return self._points.copy()
    
    def get_waypoints(self) -> List[Tuple[float, float]]:
        """Get waypoints for routing (start -> vias -> end).
        
        Returns:
            List of (lon, lat) tuples in order
        """
        return [point.as_waypoint() for point in self._points]
    
    def has_start_point(self) -> bool:
        """Check if start point exists."""
        return any(p.point_type == 'start' for p in self._points)
    
    def has_end_point(self) -> bool:
        """Check if end point exists."""
        return any(p.point_type == 'end' for p in self._points)
    
    def move_point(self, from_index: int, to_index: int) -> None:
        """Move point from one index to another.
        
        Args:
            from_index: Current index
            to_index: New index (negative = move before, positive = move after)
        """
        if not (0 <= from_index < len(self._points)):
            self.error_occurred.emit(f"Invalid from_index: {from_index}")
            return
        
        new_index = max(0, min(from_index + to_index, len(self._points) - 1))
        
        if new_index != from_index:
            point = self._points.pop(from_index)
            self._points.insert(new_index, point)
            self.points_changed.emit(self._points.copy())
    
    @staticmethod
    def _is_valid_point_type(point_type: str) -> bool:
        """Check if point type is valid."""
        return point_type in ('start', 'end', 'via')
    
    # ============ ROUTE MANAGEMENT ============
    
    def set_route(self, nodes: List[int], edges: List,
                  distance_m: float, duration_s: float,
                  coordinates: List[tuple] = None) -> None:
        """Set route information.
        
        Args:
            nodes: List of node IDs in route
            edges: List of edge dictionaries
            distance_m: Total distance in meters
            duration_s: Total duration in seconds
            coordinates: List of (lon, lat) tuples for rendering
        """
        self._route = Route(
            nodes=nodes,
            edges=edges,
            distance_m=distance_m,
            duration_s=duration_s,
            coordinates=coordinates or []
        )
        self.route_updated.emit(self._route)
        self.status_changed.emit(
            f"Route: {self._route.get_distance_km():.2f} km, "
            f"{self._route.get_duration_minutes():.1f} min"
        )
    
    def clear_route(self) -> None:
        """Clear current route."""
        self._route = None
        self.route_cleared.emit()
        self.status_changed.emit("Route cleared")
    
    def get_route(self) -> Optional[Route]:
        """Get current route.
        
        Returns:
            Route object or None
        """
        return self._route
    
    # ============ MAP STATE ============
    
    def set_zoom(self, zoom: float) -> None:
        """Set current zoom level.
        
        Args:
            zoom: Zoom level (0-24)
        """
        zoom = max(0.0, min(24.0, zoom))  # Clamp to valid range
        if self._current_zoom != zoom:
            self._current_zoom = zoom
            self.zoom_changed.emit(zoom)
    
    def get_zoom(self) -> float:
        """Get current zoom level."""
        return self._current_zoom
    
    def set_bounds(self, min_lon: float, min_lat: float,
                   max_lon: float, max_lat: float) -> None:
        """Set current map bounds.
        
        Args:
            min_lon, min_lat, max_lon, max_lat: Bounds coordinates
        """
        bounds = (min_lon, min_lat, max_lon, max_lat)
        if self._current_bounds != bounds:
            self._current_bounds = bounds
            self.bounds_changed.emit(bounds)
    
    def get_bounds(self) -> Optional[Tuple]:
        """Get current bounds."""
        return self._current_bounds
    
    def set_map_center(self, lon: float, lat: float) -> None:
        """Set map center position.
        
        Args:
            lon: Center longitude
            lat: Center latitude
        """
        center = (lon, lat)
        if self._map_center != center:
            self._map_center = center
            self.map_center_moved.emit(lon, lat)
    
    def get_map_center(self) -> Tuple[float, float]:
        """Get map center."""
        return self._map_center
    
    # ============ STATUS MANAGEMENT ============
    
    def set_status(self, message: str) -> None:
        """Set status message.
        
        Args:
            message: Status message to display
        """
        self._current_status = message
        self.status_changed.emit(message)
    
    def get_status(self) -> str:
        """Get current status."""
        return self._current_status
    
    def start_operation(self, operation_name: str) -> None:
        """Indicate operation starting.
        
        Args:
            operation_name: Name of operation (e.g., "Loading graph")
        """
        self.operation_started.emit(operation_name)
        self.set_status(operation_name + "...")
    
    def complete_operation(self, success: bool = True) -> None:
        """Indicate operation completed.
        
        Args:
            success: Whether operation was successful
        """
        self.operation_completed.emit()
        if success:
            self.set_status("Ready")
    
    def report_error(self, error_message: str) -> None:
        """Report an error.
        
        Args:
            error_message: Error message
        """
        self.error_occurred.emit(error_message)
        self.set_status(f"Error: {error_message}")
