"""OSRM Car Profile Configuration

This module implements the OSRM car.lua profile logic in Python.
It provides speed limits, turn penalties, and filtering rules for car routing.

Based on:
https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua
"""

from typing import Optional, Dict
import yaml
from pathlib import Path
from loguru import logger as log



class CarProfile:
    """Car routing profile based on OSRM car.lua
    
    This profile defines routing behavior for cars, including:
    - Speed limits by highway type
    - Turn penalties by angle
    - Road filtering rules
    - Service road penalties
    - Country-specific maxspeed rules
    
    Configuration is loaded from configs/routing/car_profile.yaml
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize profile from YAML config
        
        Args:
            config_path: Path to YAML config file
                        (default: configs/routing/car_profile.yaml)
        """
        if config_path is None:
            # Default to project root configs/routing/car_profile.yaml
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "configs" / "routing" / "car_profile.yaml"
        
        self._load_config(config_path)
        log.info(
            "car_profile_loaded",
            config_path=str(config_path),
            highway_types=len(self.HIGHWAY_SPEEDS),
            countries=len(self.MAXSPEED_TABLE)
        )
    
    def _load_config(self, config_path: Path):
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # Load all settings from config
            penalties = config['penalties']
            self.TURN_PENALTY = penalties['turn_penalty']
            self.U_TURN_PENALTY = penalties['u_turn_penalty']
            self.TRAFFIC_LIGHT_PENALTY = penalties['traffic_light_penalty']
            
            self.SPEED_TOLERANCE = config['speed_tolerance']
            
            self.HIGHWAY_SPEEDS = config['highway_speeds']
            self.SERVICE_PENALTIES = config['service_penalties']
            self.MAXSPEED_DEFAULTS = config['maxspeed_defaults']
            self.MAXSPEED_TABLE = config['maxspeed_table']
            self.SURFACE_SPEEDS = config['surface_speeds']
            self.TRACKTYPE_SPEEDS = config['tracktype_speeds']
            self.SMOOTHNESS_SPEEDS = config['smoothness_speeds']
            
            self.AVOID_HIGHWAY_TAGS = set(config['avoid_tags'])
            self.ACCESS_BLACKLIST = set(config['access_blacklist'])
            self.ACCESS_WHITELIST = set(config['access_whitelist'])
            self.BARRIER_WHITELIST = set(config['barrier_whitelist'])
            
            self.ALLOWED_HIGHWAYS = set(self.HIGHWAY_SPEEDS.keys())
            
            log.debug(
                "config_loaded",
                penalties=penalties,
                tolerance=self.SPEED_TOLERANCE,
                avoid_tags=len(self.AVOID_HIGHWAY_TAGS)
            )
            
        except Exception as e:
            log.error("config_load_failed", error=str(e), exc_info=True)
            raise
    
    def get_speed(
        self,
        highway_type: str,
        maxspeed: Optional[int] = None,
        service: Optional[str] = None,
        surface: Optional[str] = None,
        tracktype: Optional[str] = None,
        smoothness: Optional[str] = None
    ) -> float:
        """Get speed limit for highway type
        
        Args:
            highway_type: OSM highway tag value
            maxspeed: OSM maxspeed tag value (km/h)
            service: OSM service tag value (for highway=service)
            surface: OSM surface tag
            tracktype: OSM tracktype tag
            smoothness: OSM smoothness tag
            
        Returns:
            Speed limit in km/h
        """
        # Get default speed from profile
        default_speed = self.HIGHWAY_SPEEDS.get(highway_type, 25)
        
        # Apply service penalty if applicable
        if highway_type == 'service' and service:
            penalty = self.SERVICE_PENALTIES.get(service, 1.0)
            default_speed = default_speed * penalty
        
        # Apply surface speed limit
        if surface and surface in self.SURFACE_SPEEDS:
            surface_limit = self.SURFACE_SPEEDS[surface]
            if surface_limit is not None:
                default_speed = min(default_speed, surface_limit)
        
        # Apply tracktype speed limit
        if tracktype and tracktype in self.TRACKTYPE_SPEEDS:
            tracktype_limit = self.TRACKTYPE_SPEEDS[tracktype]
            default_speed = min(default_speed, tracktype_limit)
        
        # Apply smoothness speed limit
        if smoothness and smoothness in self.SMOOTHNESS_SPEEDS:
            smoothness_limit = self.SMOOTHNESS_SPEEDS[smoothness]
            default_speed = min(default_speed, smoothness_limit)
        
        # Use maxspeed if provided, with tolerance
        # Tolerance allows slight overspeeding (e.g., 20%)
        if maxspeed:
            max_allowed = default_speed * (1 + self.SPEED_TOLERANCE)
            return min(maxspeed, max_allowed)
        
        return default_speed
    
    def get_turn_penalty(
        self,
        angle_diff: float,
        is_oneway: bool = False
    ) -> float:
        """Get turn penalty in seconds based on turn angle
        
        Penalty tiers (based on OSRM logic):
        - 0-30°: 0s (straight, no penalty)
        - 30-60°: 2s (slight turn)
        - 60-120°: 7.5s (normal turn)
        - 120-150°: 12s (sharp turn)
        - 150-180°: 20s (U-turn, infinity on oneway)
        
        Args:
            angle_diff: Absolute angle difference (0-180°)
            is_oneway: True if edge is oneway (U-turn blocked)
            
        Returns:
            Turn penalty in seconds
        """
        if angle_diff < 30:
            return 0.0  # Straight
        elif angle_diff < 60:
            return 2.0  # Slight turn
        elif angle_diff < 120:
            return self.TURN_PENALTY  # Normal turn
        elif angle_diff < 150:
            return 12.0  # Sharp turn
        else:
            # U-turn
            if is_oneway:
                return float('inf')  # U-turn impossible on oneway
            return self.U_TURN_PENALTY
    
    def is_highway_allowed(self, highway_type: str, tags: dict) -> bool:
        """Check if highway type is allowed for routing
        
        Args:
            highway_type: OSM highway tag value
            tags: Full OSM tags dictionary
            
        Returns:
            True if highway is allowed for routing
        """
        # Check if highway type is in allowed list
        if highway_type not in self.ALLOWED_HIGHWAYS:
            return False
        
        # Check for avoid tags
        for tag in self.AVOID_HIGHWAY_TAGS:
            if tags.get(tag) == 'yes':
                return False
        
        # Check access restrictions
        access = tags.get('access', '')
        motor_vehicle = tags.get('motor_vehicle', '')
        motorcar = tags.get('motorcar', '')
        
        for value in [access, motor_vehicle, motorcar]:
            if value in self.ACCESS_BLACKLIST:
                return False
        
        return True
    
    @staticmethod
    def get_lane_count(tags: dict) -> int:
        """Get number of lanes from OSM tags
        
        Args:
            tags: OSM tags dictionary
            
        Returns:
            Number of lanes (default: 1)
        """
        lanes_str = tags.get('lanes', '1')
        try:
            lanes = int(lanes_str)
            return max(1, lanes)  # At least 1 lane
        except ValueError:
            return 1
    
    def parse_maxspeed(self, maxspeed_tag: Optional[str]) -> Optional[int]:
        """Parse maxspeed tag (including country-specific formats)
        
        Args:
            maxspeed_tag: OSM maxspeed tag value
            
        Returns:
            Speed in km/h, or None if not parseable
            
        Examples:
            >>> profile.parse_maxspeed('60')
            60
            >>> profile.parse_maxspeed('ru:urban')
            60
            >>> profile.parse_maxspeed('50 mph')
            80
        """
        if not maxspeed_tag:
            return None
        
        maxspeed_str = maxspeed_tag.strip().lower()
        
        # Check country-specific formats (e.g., "ru:urban", "none")
        if ':' in maxspeed_str or maxspeed_str in self.MAXSPEED_TABLE:
            if maxspeed_str in self.MAXSPEED_TABLE:
                speed = self.MAXSPEED_TABLE[maxspeed_str]
                if speed == 0:  # No default limit
                    return None
                return speed
        
        # Remove units and parse
        maxspeed_clean = maxspeed_str.replace('kmh', '').replace('km/h', '')
        maxspeed_clean = maxspeed_clean.replace('kph', '').strip()
        
        # Check for mph
        is_mph = 'mph' in maxspeed_str
        maxspeed_clean = maxspeed_clean.replace('mph', '').strip()
        
        try:
            speed = int(maxspeed_clean)
            # Convert mph to kmh
            if is_mph:
                speed = int(speed * 1.60934)
            return speed
        except ValueError:
            log.warning(
                "maxspeed_parse_failed",
                maxspeed_tag=maxspeed_tag
            )
            return None


# Global instance (singleton)
_default_profile: Optional[CarProfile] = None


def get_car_profile() -> CarProfile:
    """Get global CarProfile instance (singleton)"""
    global _default_profile
    if _default_profile is None:
        _default_profile = CarProfile()
    return _default_profile
