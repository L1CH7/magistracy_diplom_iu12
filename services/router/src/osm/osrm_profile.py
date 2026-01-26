from typing import Optional, Dict, List, Set, Any
from loguru import logger as log
from services.common.config import load_config

class CarProfile:
    """Car routing profile (OSRM-style)
    
    Loads configuration from configs/routing/car_profile.yaml
    """
    
    def __init__(self, config_path: str = "routing/car_profile.yaml"):
        """Initialize profile from YAML config
        
        Args:
            config_path: Path to traffic configuration YAML
        """
        try:
            config = load_config(config_path)
            
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
            log.error(f"config_load_failed: {str(e)}")
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
        """Get speed limit for highway type"""
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
        
        if maxspeed:
            max_allowed = default_speed * (1 + self.SPEED_TOLERANCE)
            return min(maxspeed, max_allowed)
        
        return default_speed
    
    def get_turn_penalty(self, angle_diff: float, is_oneway: bool = False) -> float:
        """Get turn penalty in seconds based on turn angle"""
        if angle_diff < 30:
            return 0.0
        elif angle_diff < 60:
            return 2.0
        elif angle_diff < 120:
            return self.TURN_PENALTY
        elif angle_diff < 150:
            return 12.0
        else:
            if is_oneway:
                return float('inf')
            return self.U_TURN_PENALTY
    
    def is_highway_allowed(self, highway_type: str, tags: dict) -> bool:
        """Check if highway type is allowed for routing"""
        if highway_type not in self.ALLOWED_HIGHWAYS:
            return False
        
        for tag in self.AVOID_HIGHWAY_TAGS:
            if tags.get(tag) == 'yes':
                return False
        
        access = tags.get('access', '')
        motor_vehicle = tags.get('motor_vehicle', '')
        motorcar = tags.get('motorcar', '')
        
        for value in [access, motor_vehicle, motorcar]:
            if value in self.ACCESS_BLACKLIST:
                return False
        
        return True
    
    @staticmethod
    def get_lane_count(tags: dict) -> int:
        lanes_str = tags.get('lanes', '1')
        try:
            lanes = int(lanes_str)
            return max(1, lanes)
        except ValueError:
            return 1
    
    def parse_maxspeed(self, maxspeed_tag: Optional[str]) -> Optional[int]:
        if not maxspeed_tag:
            return None
        
        maxspeed_str = maxspeed_tag.strip().lower()
        
        if ':' in maxspeed_str or maxspeed_str in self.MAXSPEED_TABLE:
            if maxspeed_str in self.MAXSPEED_TABLE:
                speed = self.MAXSPEED_TABLE[maxspeed_str]
                if speed == 0:
                    return None
                return speed
        
        maxspeed_clean = maxspeed_str.replace('kmh', '').replace('km/h', '')
        maxspeed_clean = maxspeed_clean.replace('kph', '').strip()
        
        is_mph = 'mph' in maxspeed_str
        maxspeed_clean = maxspeed_clean.replace('mph', '').strip()
        
        try:
            speed = int(maxspeed_clean)
            if is_mph:
                speed = int(speed * 1.60934)
            return speed
        except ValueError:
            return None

_default_profile: Optional[CarProfile] = None

def get_car_profile() -> CarProfile:
    global _default_profile
    if _default_profile is None:
        _default_profile = CarProfile()
    return _default_profile
