"""
Agent simulation module for navigation system.

Provides agent movement simulation with interpolation between route points.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import math
import time
from loguru import logger
from src.utils.instrumentation import log_function


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
    
    NEW ARCHITECTURE: Agent holds route_id reference (not snapshot).
    Route data is queried dynamically from route_cache.
    
    Attributes:
        agent_id: Unique agent identifier
        assigned_route_id: Reference to route in route_cache (DYNAMIC!)
        current_edge_index: Current position in route.edge_ids list
        current_edge_progress: Progress along current edge [0.0 to 1.0]
        sim_speed: Simulation speed multiplier (1.0 = real-time, 10.0 = 10x faster)
        start_time: Simulation start timestamp (seconds since epoch)
        total_distance_traveled_m: Total distance traveled (meters)
        is_running: Whether simulation is active
        driver_type: 'normal' (50-55 km/h) or 'hurry' (57-59 km/h)
        params: Agent physical parameters
    """
    agent_id: int
    assigned_route_id: int  # Reference to route (not snapshot!)
    current_edge_index: int = 0  # Position in route.edge_ids
    current_edge_progress: float = 0.0  # Progress on current edge [0.0-1.0]
    current_progress: float = 0.0  # Overall progress [0.0-1.0]
    sim_speed: float = 1.0  # 1x speed by default
    start_time: float = field(default_factory=time.time)
    total_distance_traveled_m: float = 0.0  # Total distance since start
    is_running: bool = True
    driver_type: str = 'normal'  # 'normal' or 'hurry'
    # Final position (saved when route completes)
    final_position: Tuple[float, float, float, int] = (0.0, 0.0, 0.0, 0)
    params: AgentParams = field(default_factory=lambda: AgentParams(
        max_speed=13.89,  # 50 km/h default
        power=1.0,
        length=4.5,
        width=1.8
    ))
    
    def get_current_position(
        self,
        route_data: dict,
        elapsed_time_sec: float,
        graph
    ) -> Tuple[float, float, float, float, int]:
        """
        Calculate current position based on elapsed time and route reference.
        
        NEW: Route data is passed dynamically (not stored in agent).
        
        Args:
            route_data: Route dict with 'edges', 'geometry', 'total_distance_m'
            elapsed_time_sec: Real time elapsed since start (seconds)
            graph: Graph instance for edge speed limits
            
        Returns:
            Tuple of (lon, lat, bearing_degrees, current_speed_mps, current_edge_id)
            bearing_degrees: Direction of movement in degrees (0-360, 0=North)
            current_speed_mps: Current speed in m/s
            current_edge_id: Current edge agent is on
        """
        if not self.is_running:
            # Return saved final position if agent finished
            if self.final_position != (0.0, 0.0, 0.0, 0):
                lon, lat, bearing, edge_id = self.final_position
                return (lon, lat, bearing, 0.0, edge_id)
            # Otherwise return first coordinate (initial state)
            route_coords = route_data.get('geometry', [])
            if route_coords:
                first_edge = route_data['edges'][0] if route_data['edges'] else 0
                return (*route_coords[0], 0.0, 0.0, first_edge)
            return (0.0, 0.0, 0.0, 0.0, 0)
        
        route_edges = route_data['edges']
        route_coords = route_data['geometry']
        route_distance_m = route_data['total_distance_m']
        
        # TRACE: Log every position calculation for teleportation debugging
        logger.trace(
            "agent_position_calc",
            agent_id=self.agent_id,
            route_id=self.assigned_route_id,
            elapsed_time=elapsed_time_sec,
            sim_speed=self.sim_speed,
            is_running=self.is_running
        )
        
        if not route_edges or not route_coords:
            logger.warning(
                "agent_empty_route",
                agent_id=self.agent_id,
                route_id=self.assigned_route_id
            )
            return (0.0, 0.0, 0.0, 0.0, 0)
        
        # Calculate distance traveled (sim_speed affects time)
        sim_time = elapsed_time_sec * self.sim_speed
        distance_traveled = sim_time * self.params.max_speed  # meters
        
        # Update total distance
        self.total_distance_traveled_m = distance_traveled
        
        # Calculate progress [0.0 to 1.0]
        if route_distance_m > 0:
            overall_progress = min(distance_traveled / route_distance_m, 1.0)
        else:
            overall_progress = 1.0
        
        # If reached end, stop and save final position
        if overall_progress >= 1.0:
            self.is_running = False
            self.current_progress = 1.0
            lon, lat = route_coords[-1]
            last_edge = route_edges[-1]
            # Calculate bearing from second-to-last to last point
            if len(route_coords) >= 2:
                bearing = self._calculate_bearing(
                    route_coords[-2], route_coords[-1]
                )
            else:
                bearing = 0.0
            # Save final position to prevent teleportation
            self.final_position = (lon, lat, bearing, last_edge)
            
            logger.success(
                "Agent reached destination",
                agent_id=self.agent_id,
                route_id=self.assigned_route_id,
                total_distance_m=self.total_distance_traveled_m,
                elapsed_time=elapsed_time_sec,
                final_position=(lon, lat)
            )
            
            return (lon, lat, bearing, 0.0, last_edge)
        
        # Find current edge based on progress
        self.current_edge_index, self.current_edge_progress = \
            self._find_edge_at_progress(overall_progress, len(route_coords))
        
        # Update overall progress for external use (e.g., ETA calculation)
        self.current_progress = overall_progress
        
        current_edge_id = route_edges[min(
            self.current_edge_index,
            len(route_edges) - 1
        )]
        
        # Calculate current speed
        current_speed = self._calculate_current_speed_dynamic(
            overall_progress, route_distance_m, route_edges, route_coords, graph
        )
        
        # Interpolate position along route
        lon, lat = self._interpolate_position(overall_progress, route_coords)
        bearing = self._calculate_bearing_at_progress(
            overall_progress, route_coords
        )
        
        # TRACE: Log calculated position for teleportation tracking
        logger.trace(
            "agent_position_result",
            agent_id=self.agent_id,
            lon=lon,
            lat=lat,
            bearing=bearing,
            speed_mps=current_speed,
            edge_id=current_edge_id,
            progress=overall_progress,
            distance_traveled_m=distance_traveled
        )
        
        return (lon, lat, bearing, current_speed, current_edge_id)
    
    def _find_edge_at_progress(
        self,
        overall_progress: float,
        total_segments: int
    ) -> Tuple[int, float]:
        """
        Find which edge (segment) agent is on based on overall progress.
        
        Args:
            overall_progress: Overall route progress [0.0-1.0]
            total_segments: Total number of segments (len(coords) - 1)
            
        Returns:
            (edge_index, progress_on_edge)
        """
        if overall_progress <= 0.0:
            return (0, 0.0)
        if overall_progress >= 1.0:
            return (total_segments - 1, 1.0)
        
        segment_progress = overall_progress * total_segments
        edge_index = int(segment_progress)
        progress_on_edge = segment_progress - edge_index
        
        # Clamp
        if edge_index >= total_segments:
            return (total_segments - 1, 1.0)
        
        return (edge_index, progress_on_edge)
    
    def _calculate_current_speed_dynamic(
        self,
        progress: float,
        route_distance_m: float,
        route_edges: List[int],
        route_coords: List[Tuple[float, float]],
        graph
    ) -> float:
        """
        Calculate current speed dynamically from graph edge data.
        
        NEW: Speed queried from graph (not stored in agent).
        Speed based on edge speed limit + RF non-penalty margin (+19 km/h).
        Driver types: 'normal' (50-55 km/h) or 'hurry' (57-59 km/h).
        Speed fluctuates randomly.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            route_distance_m: Total route distance in meters
            route_edges: List of edge IDs
            route_coords: Route coordinates
            graph: Graph instance
            
        Returns:
            Current speed in m/s
        """
        import random
        
        # Get speed limit for current edge from graph
        if route_edges and self.current_edge_index < len(route_edges):
            edge_id = route_edges[self.current_edge_index]
            edge = graph.get_edge(edge_id)
            if edge:
                speed_limit_kmh = edge.speed_limit_kmh
            else:
                speed_limit_kmh = 50.0  # fallback
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
        if len(route_coords) >= 3:
            total_segments = len(route_coords) - 1
            segment_idx = int(progress * total_segments)
            
            # Check if near a turn point
            for i in range(max(1, segment_idx - 1),
                           min(total_segments - 1, segment_idx + 2)):
                if i <= 0 or i >= len(route_coords) - 1:
                    continue
                
                # Calculate bearing change at this point
                bearing_in = self._calculate_bearing(
                    route_coords[i-1], route_coords[i]
                )
                bearing_out = self._calculate_bearing(
                    route_coords[i], route_coords[i+1]
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
    
    def _interpolate_position(
        self,
        progress: float,
        route_coords: List[Tuple[float, float]]
    ) -> Tuple[float, float]:
        """
        Interpolate position along route based on progress.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            route_coords: Route coordinates
            
        Returns:
            (lon, lat) tuple
        """
        if not route_coords:
            return (0.0, 0.0)
        
        if progress <= 0.0:
            return route_coords[0]
        if progress >= 1.0:
            return route_coords[-1]
        
        # Find which segment we're on
        total_segments = len(route_coords) - 1
        segment_progress = progress * total_segments
        segment_idx = int(segment_progress)
        
        # Clamp to valid range
        if segment_idx >= total_segments:
            return route_coords[-1]
        
        # Linear interpolation within segment
        local_progress = segment_progress - segment_idx
        p1 = route_coords[segment_idx]
        p2 = route_coords[segment_idx + 1]
        
        lon = p1[0] + (p2[0] - p1[0]) * local_progress
        lat = p1[1] + (p2[1] - p1[1]) * local_progress
        
        return (lon, lat)
    
    def _calculate_bearing_at_progress(
        self,
        progress: float,
        route_coords: List[Tuple[float, float]]
    ) -> float:
        """
        Calculate bearing (direction) at given progress.
        
        Args:
            progress: Route completion [0.0 to 1.0]
            route_coords: Route coordinates
            
        Returns:
            Bearing in degrees (0-360, 0=North, 90=East)
        """
        if not route_coords or len(route_coords) < 2:
            return 0.0
        
        # Find segment
        total_segments = len(route_coords) - 1
        segment_idx = int(progress * total_segments)
        
        # Clamp
        if segment_idx >= total_segments:
            segment_idx = total_segments - 1
        
        p1 = route_coords[segment_idx]
        p2 = route_coords[segment_idx + 1]
        
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
        self.current_edge_index = 0
        self.current_edge_progress = 0.0
        self.is_running = True
        self.final_position = (0.0, 0.0, 0.0, 0)  # Clear final position
    
    def stop(self):
        """Stop simulation."""
        self.is_running = False
    
    def resume(self):
        """Resume simulation."""
        self.is_running = True
    
    def can_switch_to_route(
        self,
        current_route_data: dict,
        new_route_data: dict,
        elapsed_time_sec: float,
        graph,
        lookahead_seconds: float = 5.0
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if remaining route overlaps with new route.
        
        Logic:
        1. Get remaining edges from current position
        2. Check each remaining edge against new route edges
        3. Ensure same edge ID AND same direction (no U-turns)
        4. Return first matching edge index in new route
        
        Args:
            current_route_data: Current route dict with edges
            new_route_data: New route dict with edges
            elapsed_time_sec: Time elapsed since start
            graph: Graph instance for edge direction checking
            lookahead_seconds: Not used (kept for compatibility)
            
        Returns:
            Tuple of (can_switch: bool, new_edge_index: Optional[int])
            If can_switch=True, new_edge_index is where agent continues
        """
        current_edges = current_route_data.get('edges', [])
        new_edges = new_route_data.get('edges', [])
        
        if not current_edges or not new_edges:
            logger.debug(
                f"can_switch: empty edges - "
                f"current={len(current_edges)}, new={len(new_edges)}"
            )
            return False, None
        
        # Get remaining edges from current position
        if self.current_edge_index >= len(current_edges):
            logger.debug(
                f"can_switch: agent at end - "
                f"edge_idx={self.current_edge_index}, "
                f"total={len(current_edges)}"
            )
            return False, None
        
        remaining_edges = current_edges[self.current_edge_index:]
        
        logger.info(
            f"can_switch_check: agent={self.agent_id}, "
            f"current_idx={self.current_edge_index}, "
            f"remaining={len(remaining_edges)}, "
            f"new_edges={len(new_edges)}"
        )
        
        # Check each remaining edge for overlap with new route
        checked_edges = 0
        for remaining_edge_id in remaining_edges:
            checked_edges += 1
            
            if remaining_edge_id in new_edges:
                # Found overlap!
                new_idx = new_edges.index(remaining_edge_id)
                
                logger.info(
                    f"can_switch: found overlap edge={remaining_edge_id}, "
                    f"new_idx={new_idx}"
                )
                
                # Get edge from graph to check direction
                edge = graph.get_edge(remaining_edge_id)
                if not edge:
                    logger.warning(
                        f"can_switch: edge {remaining_edge_id} "
                        f"not found in graph"
                    )
                    continue
                
                # Edge exists in both routes - check if SAME direction
                # Need to verify u→v direction matches in both routes
                
                # Find indices in both routes
                curr_idx = current_edges.index(remaining_edge_id)
                
                # Get previous edge in current route to check direction
                if curr_idx > 0:
                    prev_edge_curr = graph.get_edge(
                        current_edges[curr_idx - 1]
                    )
                    # Check if prev.v == edge.u (correct direction chain)
                    if prev_edge_curr and prev_edge_curr.v != edge.u:
                        logger.warning(
                            f"can_switch: wrong direction in current route - "
                            f"prev.v={prev_edge_curr.v}, edge.u={edge.u}"
                        )
                        continue
                
                # Get previous edge in new route to check direction
                if new_idx > 0:
                    prev_edge_new = graph.get_edge(new_edges[new_idx - 1])
                    # Check if prev.v == edge.u (correct direction chain)
                    if prev_edge_new and prev_edge_new.v != edge.u:
                        logger.warning(
                            f"can_switch: wrong direction in new route - "
                            f"prev.v={prev_edge_new.v}, edge.u={edge.u}"
                        )
                        continue
                
                # Both routes use this edge in same direction!
                logger.info(
                    f"can_switch: SUCCESS - edge={remaining_edge_id}, "
                    f"new_idx={new_idx}"
                )
                return True, new_idx
        
        # No valid overlap found
        logger.warning(
            f"can_switch: no overlap found after checking "
            f"{checked_edges} remaining edges"
        )
        return False, None


@dataclass
class AgentState:
    """Legacy agent state (kept for compatibility)."""
    route_nodes: List[int]
    index: int = 0
    position_lat: float = 0.0
    position_lon: float = 0.0
    speed: float = 0.0
