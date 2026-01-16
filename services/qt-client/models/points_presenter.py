"""Points presenter: wraps raw points array with styling."""
from typing import List, Dict, Any
from loguru import logger

log = logger


class PointsPresenter:
    """Presenter for points array with position-based styling.
    
    Takes raw points array (with their original colors) and produces
    styled points where From/To get display overrides.
    
    This ensures consistent styling between sandwich widget and map.
    """
    
    # Display colors for From/To/Via
    FROM_COLOR = '#2563eb'  # Blue
    TO_COLOR = '#dc2626'  # Red
    VIA_DEFAULT = '#8b5cf6'  # Purple
    
    def __init__(self, points: List[Dict[str, Any]] = None):
        """Initialize presenter with points array.
        
        Args:
            points: List of point dicts with lon, lat, color
        """
        self._raw_points = points if points else []
    
    def set_points(self, points: List[Dict[str, Any]]) -> None:
        """Update the raw points array.
        
        Args:
            points: New list of point dicts
        """
        self._raw_points = points if points else []
    
    def get_raw_points(self) -> List[Dict[str, Any]]:
        """Get the raw points array (for sending to server).
        
        Returns:
            List of original point dicts with their original colors
        """
        return self._raw_points.copy()
    
    def get_styled_points(self) -> List[Dict[str, Any]]:
        """Get points with display styling applied.
        
        Display override logic:
        - points[0] (From): white circle + blue border
        - points[-1] (To): white circle + red border
        - all others (Via): original color fill + black border
        
        Original colors are NEVER modified - only display override applied.
        
        Returns:
            List of point dicts with display_color and display_type fields
        """
        styled = []
        n = len(self._raw_points)
        
        for idx, point in enumerate(self._raw_points):
            styled_point = point.copy()
            
            if idx == 0:
                # From (points.begin()): override display style
                styled_point['display_color'] = self.FROM_COLOR
                styled_point['display_type'] = 'from'
            elif n > 1 and idx == n - 1:
                # To (points.end(), if != begin): override display style
                styled_point['display_color'] = self.TO_COLOR
                styled_point['display_type'] = 'to'
            else:
                # Via: use original color from point data
                orig_color = point.get('color', self.VIA_DEFAULT)
                styled_point['display_color'] = orig_color
                styled_point['display_type'] = 'via'
            
            styled.append(styled_point)
        
        return styled
    
    def count(self) -> int:
        """Get number of points.
        
        Returns:
            Number of points in array
        """
        return len(self._raw_points)
    
    def is_empty(self) -> bool:
        """Check if points array is empty.
        
        Returns:
            True if no points
        """
        return len(self._raw_points) == 0
    
    def move_point(self, from_idx: int, to_idx: int) -> bool:
        """Move point from one position to another.
        
        Args:
            from_idx: Source index
            to_idx: Destination index
            
        Returns:
            True if move was successful
        """
        if not (0 <= from_idx < len(self._raw_points)):
            return False
        if not (0 <= to_idx < len(self._raw_points)):
            return False
        
        log.info(
            "presenter_move_point_BEFORE",
            from_idx=from_idx,
            to_idx=to_idx,
            count=len(self._raw_points),
            colors_before=[p.get('color', 'N/A') for p in self._raw_points]
        )
        
        point = self._raw_points.pop(from_idx)
        self._raw_points.insert(to_idx, point)
        
        log.info(
            "presenter_move_point_AFTER",
            count=len(self._raw_points),
            colors_after=[p.get('color', 'N/A') for p in self._raw_points]
        )
        
        return True
    
    def remove_point(self, idx: int) -> bool:
        """Remove point at index.
        
        Args:
            idx: Index to remove
            
        Returns:
            True if removal was successful
        """
        if not (0 <= idx < len(self._raw_points)):
            return False
        
        self._raw_points.pop(idx)
        return True
    
    def get_from_via_to(self) -> Dict[str, Any]:
        """Get points in From/Via/To format for compatibility.
        
        Returns:
            Dict with start, via, end keys
        """
        if len(self._raw_points) == 0:
            return {'start': None, 'via': [], 'end': None}
        
        start = self._raw_points[0]
        end = self._raw_points[-1] if len(self._raw_points) > 1 else None
        via = self._raw_points[1:-1] if len(self._raw_points) > 2 else []
        
        return {'start': start, 'via': via, 'end': end}
