"""
Pure functions for agent movement calculations.

ALL functions here are PURE:
- No side effects
- Same input = same output
- No mutation of input data
- No global state access

This design allows:
1. Easy testing (no mocks needed)
2. Numpy vectorization (batch processing 1000 agents)
3. Parallelization (no shared state)
4. Replay/debugging (deterministic)
"""

import math
from typing import Tuple, Optional, Dict
from src.shared.models.agent import AgentState, TeleportAlert


def move(
    state: AgentState,
    dt: float,
    edge_speeds: Dict[int, float],
    edge_geometries: Dict[
        int, Tuple[Tuple[float, float], Tuple[float, float]]
    ],
    turn_angles: Dict[Tuple[int, int], float]
) -> AgentState:
    """
    Pure function to update agent position after dt seconds.
    
    NO SIDE EFFECTS - returns new state, doesn't modify input!
    
    Args:
        state: Current agent state
        dt: Time delta in seconds (e.g., 0.05 for 20 FPS)
        edge_speeds: Dict[edge_id -> speed_limit_kmh]
        edge_geometries: Dict[edge_id -> (start_point, end_point)]
        turn_angles: Dict[(edge_in, edge_out) -> angle_degrees]
        
    Returns:
        New AgentState with updated position
        
    Algorithm:
    1. Check if agent reached destination
    2. Calculate current speed (with turn penalties, accel/decel)
    3. Calculate distance traveled in dt
    4. Update position along edge
    5. If edge complete, move to next edge
    6. Return new state
    """
    if not state.is_running or state.reached_destination:
        return state  # Return as-is
    
    if not state.route_edge_ids:
        # No route - stop
        return AgentState(
            **{
                **state.__dict__,
                'is_running': False,
                'reached_destination': True
            }
        )
    
    # Get current edge
    current_edge_id = state.route_edge_ids[state.route_index]
    
    # Calculate current speed
    current_speed = _calculate_speed(
        state=state,
        edge_speeds=edge_speeds,
        turn_angles=turn_angles
    )
    
    # Distance traveled in dt
    distance_m = current_speed * dt
    
    # Get edge geometry
    edge_geom = edge_geometries.get(current_edge_id)
    if not edge_geom:
        # Edge not found - can't move
        return state
    
    start_point, end_point = edge_geom
    edge_length_m = _haversine_distance(start_point, end_point)
    
    if edge_length_m == 0:
        # Zero-length edge, skip to next
        return _advance_to_next_edge(state)
    
    # Update progress along edge
    progress_delta = distance_m / edge_length_m
    new_edge_progress = state.edge_progress + progress_delta
    
    # Check if completed edge
    if new_edge_progress >= 1.0:
        # Reached end of edge
        if state.route_index >= len(state.route_edge_ids) - 1:
            # This was last edge - destination reached!
            return AgentState(
                agent_id=state.agent_id,
                lat=end_point[1],
                lon=end_point[0],
                edge_id=current_edge_id,
                edge_progress=1.0,
                route_edge_ids=state.route_edge_ids,
                route_index=state.route_index,
                current_speed_mps=0.0,
                bearing_degrees=_calculate_bearing(start_point, end_point),
                start_time=state.start_time,
                elapsed_time=state.elapsed_time + dt,
                is_running=False,
                reached_destination=True,
                config=state.config,
                total_distance_m=state.total_distance_m + distance_m
            )
        else:
            # Move to next edge
            edge_dist_remaining = edge_length_m * (1.0 - state.edge_progress)
            dist_remaining = distance_m - edge_dist_remaining
            
            if progress_delta > 0:
                dt_remaining = dt * (1.0 - (1.0 - state.edge_progress) /
                                     progress_delta)
            else:
                dt_remaining = 0
            
            return _advance_to_next_edge(
                state,
                distance_remaining=dist_remaining,
                dt_remaining=dt_remaining,
                edge_geometries=edge_geometries,
                edge_speeds=edge_speeds,
                turn_angles=turn_angles
            )
    
    # Still on same edge - interpolate position
    new_lat, new_lon = _interpolate_position(
        start_point, end_point, new_edge_progress
    )
    
    new_bearing = _calculate_bearing(start_point, end_point)
    
    # Return new state (immutable)
    return AgentState(
        agent_id=state.agent_id,
        lat=new_lat,
        lon=new_lon,
        edge_id=current_edge_id,
        edge_progress=new_edge_progress,
        route_edge_ids=state.route_edge_ids,
        route_index=state.route_index,
        current_speed_mps=current_speed,
        bearing_degrees=new_bearing,
        start_time=state.start_time,
        elapsed_time=state.elapsed_time + dt,
        is_running=True,
        reached_destination=False,
        config=state.config,
        total_distance_m=state.total_distance_m + distance_m
    )


def _advance_to_next_edge(
    state: AgentState,
    distance_remaining: float = 0.0,
    dt_remaining: float = 0.0,
    edge_geometries: Optional[Dict] = None,
    edge_speeds: Optional[Dict] = None,
    turn_angles: Optional[Dict] = None
) -> AgentState:
    """
    Helper to advance agent to next edge in route.
    
    If distance_remaining > 0, continues moving on new edge.
    """
    new_index = state.route_index + 1
    
    if new_index >= len(state.route_edge_ids):
        # No more edges
        return AgentState(
            **{
                **state.__dict__,
                'is_running': False,
                'reached_destination': True
            }
        )
    
    next_edge_id = state.route_edge_ids[new_index]
    
    # Create state at start of next edge
    new_state = AgentState(
        agent_id=state.agent_id,
        lat=state.lat,
        lon=state.lon,
        edge_id=next_edge_id,
        edge_progress=0.0,
        route_edge_ids=state.route_edge_ids,
        route_index=new_index,
        current_speed_mps=state.current_speed_mps,
        bearing_degrees=state.bearing_degrees,
        start_time=state.start_time,
        elapsed_time=state.elapsed_time,
        is_running=True,
        reached_destination=False,
        config=state.config,
        total_distance_m=state.total_distance_m
    )
    
    # If still have distance to cover, recurse
    if distance_remaining > 0 and dt_remaining > 0 and edge_geometries:
        return move(
            new_state,
            dt_remaining,
            edge_speeds or {},
            edge_geometries,
            turn_angles or {}
        )
    
    return new_state


def _calculate_speed(
    state: AgentState,
    edge_speeds: Dict[int, float],
    turn_angles: Dict[Tuple[int, int], float]
) -> float:
    """
    Calculate current speed based on:
    - Edge speed limit
    - Agent config (max_speed, driver_mode)
    - Turn penalties
    - Acceleration/deceleration zones
    
    Returns: speed in m/s
    """
    config = state.config
    current_edge_id = state.route_edge_ids[state.route_index]
    
    # Get speed limit for current edge
    speed_limit_kmh = edge_speeds.get(current_edge_id, 50.0)
    
    # RF non-penalty margin: speed_limit + 19 km/h
    max_allowed_kmh = speed_limit_kmh + 19.0
    
    # Driver mode adjustments
    if config.driver_mode == 'hurry':
        target_kmh = min(max_allowed_kmh, config.max_speed_kmh)
    elif config.driver_mode == 'patient':
        target_kmh = min(max_allowed_kmh * 0.85, config.max_speed_kmh * 0.9)
    else:  # normal
        target_kmh = min(max_allowed_kmh * 0.92, config.max_speed_kmh)
    
    max_speed_mps = target_kmh / 3.6
    
    # Acceleration zone (first 5% of edge)
    if state.edge_progress < 0.05:
        accel_factor = state.edge_progress / 0.05
        return max_speed_mps * accel_factor
    
    # Deceleration zone (last 10% of edge)
    if state.edge_progress > 0.90:
        decel_factor = (1.0 - state.edge_progress) / 0.10
        return max_speed_mps * decel_factor
    
    # Turn penalty (if approaching next edge with turn)
    if state.route_index < len(state.route_edge_ids) - 1:
        next_edge_id = state.route_edge_ids[state.route_index + 1]
        turn_key = (current_edge_id, next_edge_id)
        turn_angle = turn_angles.get(turn_key, 0.0)
        
        # Approaching turn in last 10% of edge
        if turn_angle > 30 and state.edge_progress > 0.90:
            # Reduce speed based on turn angle
            turn_factor = config.turn_speed_multiplier
            if turn_angle > 60:
                turn_factor *= 0.7  # Sharp turn
            return max_speed_mps * turn_factor
    
    # Cruising speed
    return max_speed_mps


def detect_teleport(
    prev_state: AgentState,
    new_state: AgentState,
    dt: float,
    threshold_multiplier: float = 1.5
) -> Optional[TeleportAlert]:
    """
    Detect if agent teleported (moved too far for given dt).
    
    Pure function - just compares states.
    
    Args:
        prev_state: Previous agent state
        new_state: New agent state (after move)
        dt: Time delta
        threshold_multiplier: Max allowed distance =
            max_speed * dt * multiplier
        
    Returns:
        TeleportAlert if teleportation detected, None otherwise
    """
    if not prev_state.is_running or not new_state.is_running:
        return None  # Don't check when stopped
    
    # Calculate actual distance moved
    actual_distance = _haversine_distance(
        (prev_state.lon, prev_state.lat),
        (new_state.lon, new_state.lat)
    )
    
    # Calculate expected max distance
    max_speed_mps = new_state.config.max_speed_kmh / 3.6
    expected_max_distance = max_speed_mps * dt * threshold_multiplier
    
    if actual_distance > expected_max_distance:
        return TeleportAlert(
            agent_id=new_state.agent_id,
            timestamp=new_state.elapsed_time,
            expected_distance_m=expected_max_distance,
            actual_distance_m=actual_distance,
            lat=new_state.lat,
            lon=new_state.lon
        )
    
    return None


def can_switch_route(
    state: AgentState,
    new_route_edge_ids: Tuple[int, ...],
    graph_edges: Dict[int, Tuple[int, int]]  # edge_id -> (u_node, v_node)
) -> Tuple[bool, Optional[int]]:
    """
    Check if agent can switch to new route at current position.
    
    Logic:
    - Find remaining edges in current route
    - Check if any remaining edge exists in new route
    - Verify same direction (no U-turns)
    
    Args:
        state: Current agent state
        new_route_edge_ids: New route edge IDs
        graph_edges: Dict mapping edge_id to (source_node, target_node)
        
    Returns:
        (can_switch: bool, new_route_index: Optional[int])
        If can_switch=True, new_route_index is where to continue
    """
    if not state.is_running or state.reached_destination:
        return False, None
    
    # Get remaining edges from current position
    remaining_edges = state.route_edge_ids[state.route_index:]
    
    if not remaining_edges:
        return False, None
    
    # Check each remaining edge
    for remaining_edge_id in remaining_edges:
        if remaining_edge_id in new_route_edge_ids:
            # Found overlap
            new_index = new_route_edge_ids.index(remaining_edge_id)
            
            # Verify direction (check if edge connects properly)
            edge_nodes = graph_edges.get(remaining_edge_id)
            if not edge_nodes:
                continue
            
            u_node, v_node = edge_nodes
            
            # If not first edge in new route, check connection
            if new_index > 0:
                prev_edge_id = new_route_edge_ids[new_index - 1]
                prev_nodes = graph_edges.get(prev_edge_id)
                if prev_nodes:
                    prev_u, prev_v = prev_nodes
                    # Check if edges connect: prev.v == current.u
                    if prev_v != u_node:
                        continue  # Wrong direction
            
            # Valid switch point found!
            return True, new_index
    
    return False, None


# ============================================================================
# Helper functions (geometry, math)
# ============================================================================

def _haversine_distance(
    point1: Tuple[float, float],
    point2: Tuple[float, float]
) -> float:
    """
    Calculate distance between two points using Haversine formula.
    
    Args:
        point1: (lon, lat) in degrees
        point2: (lon, lat) in degrees
        
    Returns:
        Distance in meters
    """
    lon1, lat1 = point1
    lon2, lat2 = point2
    
    # Earth radius in meters
    R = 6371000
    
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def _interpolate_position(
    start_point: Tuple[float, float],
    end_point: Tuple[float, float],
    progress: float
) -> Tuple[float, float]:
    """
    Linear interpolation between two points.
    
    Args:
        start_point: (lon, lat)
        end_point: (lon, lat)
        progress: 0.0 to 1.0
        
    Returns:
        (lat, lon) at progress
    """
    lon1, lat1 = start_point
    lon2, lat2 = end_point
    
    lat = lat1 + (lat2 - lat1) * progress
    lon = lon1 + (lon2 - lon1) * progress
    
    return lat, lon


def _calculate_bearing(
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
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)
    
    y = math.sin(dlon_rad) * math.cos(lat2_rad)
    x = (math.cos(lat1_rad) * math.sin(lat2_rad) -
         math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad))
    
    bearing_rad = math.atan2(y, x)
    bearing_deg = math.degrees(bearing_rad)
    
    # Normalize to 0-360
    return (bearing_deg + 360) % 360
