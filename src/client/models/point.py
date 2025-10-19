"""Point model."""
from dataclasses import dataclass
from typing import Tuple


@dataclass
class Point:
    """Navigation point (start, end, via).
    
    Attributes:
        point_type: 'start', 'end', or 'via'
        lon: Longitude
        lat: Latitude
        color: Display color (hex like '#FF0000')
        label: Display label (like 'Start', 'End', 'Via 1')
    """
    point_type: str  # 'start', 'end', 'via'
    lon: float
    lat: float
    color: str = '#0088FF'
    label: str = ''
    
    def __post_init__(self):
        """Set default label based on type."""
        if not self.label:
            if self.point_type == 'start':
                self.label = 'Start'
                self.color = '#00FF00'
            elif self.point_type == 'end':
                self.label = 'End'
                self.color = '#FF0000'
            elif self.point_type == 'via':
                self.label = 'Via'
                self.color = '#FFFF00'
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            'type': self.point_type,
            'lon': self.lon,
            'lat': self.lat,
            'color': self.color,
            'label': self.label,
        }
    
    def as_waypoint(self) -> Tuple[float, float]:
        """Get as (lon, lat) tuple for routing."""
        return (self.lon, self.lat)
