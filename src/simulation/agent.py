"""
Agent simulation module for navigation system.

Provides agent movement simulation with interpolation between route points.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import math
import time


@dataclass
class AgentParams:
    """Agent physical parameters."""
    max_speed: float  # m/s
    power: float      # abstract acceleration capability
    length: float     # meters
    width: float      # meters


@dataclass
class SimulationAgent:
    """
    Simulation agent that moves along a route.
    
    Attributes:
        agent_id: Unique agent identifier
        route_edges: List of edge IDs (route path)
        route_coords: List of (lon, lat) coordinates for the full route
        edge_speed_limits: List of speed limits (km/h) for each edge
        sim_speed: Simulation speed multiplier (1.0 = real-time, 10.0 = 10x faster)
        start_time: Simulation start timestamp (seconds since epoch)
        current_progress: Progress along route [0.0 to 1.0]
        is_running: Whether simulation is active
        driver_type: 'normal' (50-55 km/h) or 'hurry' (57-59 km/h)
        params: Agent physical parameters
    """
    agent_id: int
    route_edges: List[int]
    route_coords: List[Tuple[float, float]]  # [(lon, lat), ...]
    edge_speed_limits: List[float] = field(default_factory=list)  # km/h per edge
    sim_speed: float = 1.0  # 1x speed by default
    start_time: float = field(default_factory=time.time)
    current_progress: float = 0.0  # 0.0 to 1.0
    is_running: bool = True
    driver_type: str = 'normal'  # 'normal' or 'hurry'
    params: AgentParams = field(default_factory=lambda: AgentParams(
        max_speed=13.89,  # 50 km/h default
        power=1.0,
        length=4.5,
        width=1.8
    ))
    
    def get_current_position(
        self,
        route_distance_m: float,
        elapsed_time_sec: float
    ) -> Tuple[float, float, float, float]:
        """
        Calculate current position based on elapsed time.
        
        Args:
            route_distance_m: Total route distance in meters
            elapsed_time_sec: Real time elapsed since start (seconds)
            
        Returns:
            Tuple of (lon, lat, bearing_degrees, current_speed_mps)
            bearing_degrees: Direction of movement in degrees (0-360, 0=North)
            current_speed_mps: Current speed in m/s (considering acceleration/deceleration)
        """
        if not self.is_running or not self.route_coords:
            # Return first coordinate if not running
            if self.route_coords:
                return (*self.route_coords[0], 0.0, 0.0)
            return (0.0, 0.0, 0.0, 0.0)
        
        # Calculate distance traveled (sim_speed affects time)
        sim_time = elapsed_time_sec * self.sim_speed
        distance_traveled = sim_time * self.params.max_speed  # meters
        
        # Calculate progress [0.0 to 1.0]
        if route_distance_m > 0:
            self.current_progress = min(distance_traveled / route_distance_m, 1.0)
        else:
            self.current_progress = 1.0
        
        # Calculate current speed with acceleration/deceleration
        current_speed = self._calculate_current_speed(
            self.current_progress, route_distance_m
        )
        
        # If reached end, stop
        if self.current_progress >= 1.0:
            self.is_running = False
            # Return last coordinate
            lon, lat = self.route_coords[-1]
            # Calculate bearing from second-to-last to last point
            if len(self.route_coords) >= 2:
                bearing = self._calculate_bearing(
                    self.route_coords[-2], self.route_coords[-1]
                )
            else:
                bearing = 0.0
            return (lon, lat, bearing, 0.0)
        
        # Interpolate position along route
        lon, lat = self._interpolate_position(self.current_progress)
        bearing = self._calculate_bearing_at_progress(self.current_progress)
        
        return (lon, lat, bearing, current_speed)
    
    def _calculate_current_speed(
        self,
        progress: float,
        route_distance_m: float
    ) -> float:
        """
        Calculate current speed with acceleration/deceleration.
        
        Speed based on edge speed limit + RF non-penalty margin (+19 km/h).
        Driver types: 'normal' (50-55 km/h) or 'hurry' (57-59 km/h).
        Speed fluctuates randomly.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            route_distance_m: Total route distance in meters
            
        Returns:
            Current speed in m/s
        """
        import random
        
        # Get speed limit for current segment
        if self.edge_speed_limits and len(self.route_coords) > 1:
            total_segments = len(self.route_coords) - 1
            segment_idx = min(
                int(progress * total_segments),
                len(self.edge_speed_limits) - 1
            )
            speed_limit_kmh = self.edge_speed_limits[segment_idx]
        else:
            speed_limit_kmh = 50.0  # fallback
        
        # RF non-penalty margin: +19 km/h
        max_allowed_kmh = speed_limit_kmh + 19
        
        # Driver type: normal (50-55 range) or hurry (57-59 range)
        if self.driver_type == 'hurry':
            target_kmh = max_allowed_kmh - random.uniform(0, 2)  # 57-59
        else:
            target_kmh = max_allowed_kmh - random.uniform(4, 9)  # 50-55
        
        # Clamp to reasonable range
        target_kmh = min(target_kmh, max_allowed_kmh)
        target_kmh = max(target_kmh, speed_limit_kmh * 0.8)  # min 80% of limit
        
        max_speed = target_kmh / 3.6  # convert to m/s
        
        # Acceleration/deceleration zones
        accel_zone = 0.05  # First 5% of route
        decel_zone = 0.10  # Last 10% of route
        turn_zone = 0.02   # 2% before/after each turn
        
        # Start acceleration
        if progress < accel_zone:
            # Linear acceleration from 0 to max_speed
            return max_speed * (progress / accel_zone)
        
        # End deceleration
        if progress > (1.0 - decel_zone):
            # Linear deceleration from max_speed to 0
            remaining = 1.0 - progress
            return max_speed * (remaining / decel_zone)
        
        # Check for turns (change in bearing between segments)
        if len(self.route_coords) >= 3:
            total_segments = len(self.route_coords) - 1
            segment_idx = int(progress * total_segments)
            
            # Check if near a turn point
            for i in range(max(1, segment_idx - 1), 
                          min(total_segments - 1, segment_idx + 2)):
                if i <= 0 or i >= len(self.route_coords) - 1:
                    continue
                
                # Calculate bearing change at this point
                bearing_in = self._calculate_bearing(
                    self.route_coords[i-1], self.route_coords[i]
                )
                bearing_out = self._calculate_bearing(
                    self.route_coords[i], self.route_coords[i+1]
                )
                bearing_change = abs(bearing_out - bearing_in)
                # Normalize to 0-180
                if bearing_change > 180:
                    bearing_change = 360 - bearing_change
                
                # If significant turn (>30 degrees), slow down
                if bearing_change > 30:
                    turn_progress = float(i) / total_segments
                    distance_to_turn = abs(progress - turn_progress)
                    
                    if distance_to_turn < turn_zone:
                        # Reduce speed near turn (50-100% of max_speed)
                        turn_factor = 0.5 + 0.5 * (distance_to_turn / turn_zone)
                        return max_speed * turn_factor
        
        # Cruising speed
        return max_speed
    
    def _interpolate_position(self, progress: float) -> Tuple[float, float]:
        """
        Interpolate position along route based on progress.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            
        Returns:
            (lon, lat) tuple
        """
        if not self.route_coords:
            return (0.0, 0.0)
        
        if progress <= 0.0:
            return self.route_coords[0]
        if progress >= 1.0:
            return self.route_coords[-1]
        
        # Find which segment we're on
        total_segments = len(self.route_coords) - 1
        segment_progress = progress * total_segments
        segment_idx = int(segment_progress)
        
        # Clamp to valid range
        if segment_idx >= total_segments:
            return self.route_coords[-1]
        
        # Linear interpolation within segment
        local_progress = segment_progress - segment_idx
        p1 = self.route_coords[segment_idx]
        p2 = self.route_coords[segment_idx + 1]
        
        lon = p1[0] + (p2[0] - p1[0]) * local_progress
        lat = p1[1] + (p2[1] - p1[1]) * local_progress
        
        return (lon, lat)
    
    def _calculate_bearing_at_progress(self, progress: float) -> float:
        """
        Calculate bearing (direction) at given progress.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            
        Returns:
            Bearing in degrees (0-360, 0=North, 90=East)
        """
        if not self.route_coords or len(self.route_coords) < 2:
            return 0.0
        
        # Find segment
        total_segments = len(self.route_coords) - 1
        segment_idx = int(progress * total_segments)
        
        # Clamp
        if segment_idx >= total_segments:
            segment_idx = total_segments - 1
        
        p1 = self.route_coords[segment_idx]
        p2 = self.route_coords[segment_idx + 1]
        
        return self._calculate_bearing(p1, p2)
    
    def _calculate_bearing(
        self,
        point1: Tuple[float, float],
        point2: Tuple[float, float]
    ) -> float:
        """
        Calculate bearing from point1 to point2.
        
        Args:
            point1: (lon, lat) in degrees
            point2: (lon, lat) in degrees
            
        Returns:
            Bearing in degrees (0-360, 0=North, 90=East)
        """
        lon1, lat1 = point1
        lon2, lat2 = point2
        
        # Convert to radians
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlon_rad = math.radians(lon2 - lon1)
        
        # Calculate bearing
        y = math.sin(dlon_rad) * math.cos(lat2_rad)
        x = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad))
        
        bearing_rad = math.atan2(y, x)
        bearing_deg = math.degrees(bearing_rad)
        
        # Normalize to 0-360
        bearing_deg = (bearing_deg + 360) % 360
        
        return bearing_deg
    
    def restart(self):
        """Restart simulation from beginning."""
        self.start_time = time.time()
        self.current_progress = 0.0
        self.is_running = True
    
    def stop(self):
        """Stop simulation."""
        self.is_running = False
    
    def resume(self):
        """Resume simulation."""
        self.is_running = True


@dataclass
class AgentState:
    """Legacy agent state (kept for compatibility)."""
    route_nodes: List[int]
    index: int = 0
    position_lat: float = 0.0
    position_lon: float = 0.0
    speed: float = 0.0
