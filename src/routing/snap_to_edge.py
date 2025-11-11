"""
Edge snapping module for point-to-edge projection.

This module handles snapping user-clicked points to actual road edges,
including position calculation and bearing computation for turn costs.

Author: bmstu/diplom
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass
import math

from src.data.postgis_manager import PostGISManager
from src.utils.logger import setup_logger


log = setup_logger(__name__)


@dataclass
class EdgeSnap:
    """Result of snapping a point to an edge."""
    edge_id: int
    start_node_id: int
    end_node_id: int
    length_m: float
    fraction: float  # Position on edge: 0.0 = start, 1.0 = end
    position_m: float  # Absolute position in meters from start
    distance_to_edge_m: float  # Perpendicular distance from point to edge
    bearing: float  # Edge bearing in degrees (0-360, 0=North, 90=East)
    geometry: List[Tuple[float, float]]  # Edge geometry [(lon, lat), ...]

    def __repr__(self) -> str:
        return (f"EdgeSnap(edge={self.edge_id}, "
                f"fraction={self.fraction:.3f}, "
                f"position_m={self.position_m:.1f}, "
                f"bearing={self.bearing:.1f}°)")


def snap_point_to_edges(
    db: PostGISManager,
    lat: float,
    lon: float,
    k: int = 5,
    max_distance_m: float = 100.0
) -> List[EdgeSnap]:
    """
    Snap a point to k nearest edges using PostGIS.

    Args:
        db: PostGIS manager instance
        lat: Point latitude
        lon: Point longitude
        k: Number of nearest edges to return
        max_distance_m: Maximum distance to consider (filter far edges)

    Returns:
        List of EdgeSnap objects, sorted by distance (closest first)

    Example:
        >>> db = PostGISManager()
        >>> snaps = snap_point_to_edges(db, 55.751, 37.618, k=5)
        >>> best = snaps[0]
        >>> print(f"Snapped to edge {best.edge_id} at {best.position_m:.1f}m")
    """
    query = """
    WITH point AS (
        SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
    )
    SELECT
        e.id,
        e.start_node_id,
        e.end_node_id,
        e.length_m,
        ST_LineLocatePoint(e.geometry, point.geom) AS fraction,
        ST_Distance(
            e.geometry::geography,
            point.geom::geography
        ) AS distance_m,
        degrees(ST_Azimuth(
            ST_StartPoint(e.geometry),
            ST_EndPoint(e.geometry)
        )) AS bearing_raw,
        ST_AsText(e.geometry) AS geometry_wkt
    FROM edges e, point
    WHERE ST_DWithin(
        e.geometry::geography,
        point.geom::geography,
        %s
    )
    ORDER BY e.geometry <-> point.geom
    LIMIT %s
    """

    try:
        results = db.execute_query(
            query,
            (lon, lat, max_distance_m, k)
        )

        if not results:
            log.warning(
                "No edges found within distance",
                lat=lat,
                lon=lon,
                max_distance_m=max_distance_m
            )
            return []

        snaps = []
        for row in results:
            edge_id = row[0]
            start_node_id = row[1]
            end_node_id = row[2]
            length_m = row[3]
            fraction = row[4]
            distance_m = row[5]
            bearing_raw = row[6]
            geometry_wkt = row[7]

            # Parse geometry WKT: "LINESTRING(lon1 lat1, lon2 lat2, ...)"
            coords_str = (geometry_wkt
                          .replace("LINESTRING(", "")
                          .replace(")", ""))
            coords = []
            for coord_pair in coords_str.split(","):
                lon_str, lat_str = coord_pair.strip().split()
                coords.append((float(lon_str), float(lat_str)))

            # Normalize bearing to 0-360
            bearing = bearing_raw if bearing_raw is not None else 0.0
            if bearing < 0:
                bearing += 360.0

            # Calculate absolute position in meters
            position_m = fraction * length_m

            snap = EdgeSnap(
                edge_id=edge_id,
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                length_m=length_m,
                fraction=fraction,
                position_m=position_m,
                distance_to_edge_m=distance_m,
                bearing=bearing,
                geometry=coords
            )

            snaps.append(snap)
            log.debug(
                "Edge snap candidate",
                edge_id=edge_id,
                fraction=f"{fraction:.3f}",
                distance_m=f"{distance_m:.2f}",
                bearing=f"{bearing:.1f}°"
            )

        best_dist = (f"{snaps[0].distance_to_edge_m:.2f}"
                     if snaps else None)
        log.info(
            "Point snapped to edges",
            lat=lat,
            lon=lon,
            num_snaps=len(snaps),
            best_distance_m=best_dist
        )

        return snaps

    except Exception as e:
        log.error("Failed to snap point to edges",
                  error=str(e), lat=lat, lon=lon)
        raise


def interpolate_edge_segment(
    geometry: List[Tuple[float, float]],
    start_fraction: float,
    end_fraction: float
) -> List[Tuple[float, float]]:
    """
    Extract segment of edge geometry between two fractions.

    Args:
        geometry: Edge geometry as [(lon, lat), ...]
        start_fraction: Start position (0.0 = beginning of edge)
        end_fraction: End position (1.0 = end of edge)

    Returns:
        List of (lon, lat) coordinates for the segment

    Example:
        >>> geom = [(37.0, 55.0), (37.1, 55.1), (37.2, 55.2)]
        >>> segment = interpolate_edge_segment(geom, 0.0, 0.5)
        # Returns first half of geometry
    """
    if not geometry:
        return []

    if start_fraction >= end_fraction:
        return []

    # Calculate cumulative distances
    cumulative_dist = [0.0]
    for i in range(len(geometry) - 1):
        p1 = geometry[i]
        p2 = geometry[i + 1]
        dist = haversine_distance(p1[1], p1[0], p2[1], p2[0])
        cumulative_dist.append(cumulative_dist[-1] + dist)

    total_dist = cumulative_dist[-1]
    if total_dist == 0:
        return [geometry[0]]

    start_dist = start_fraction * total_dist
    end_dist = end_fraction * total_dist

    # Find segment points
    result = []

    # Add interpolated start point
    start_idx = 0
    for i in range(len(cumulative_dist) - 1):
        if cumulative_dist[i] <= start_dist <= cumulative_dist[i + 1]:
            start_idx = i
            # Interpolate point on segment i->i+1
            segment_dist = cumulative_dist[i + 1] - cumulative_dist[i]
            if segment_dist > 0:
                t = (start_dist - cumulative_dist[i]) / segment_dist
                p1 = geometry[i]
                p2 = geometry[i + 1]
                interp_lon = p1[0] + t * (p2[0] - p1[0])
                interp_lat = p1[1] + t * (p2[1] - p1[1])
                result.append((interp_lon, interp_lat))
            else:
                result.append(geometry[i])
            break

    # Add all intermediate points
    for i in range(start_idx + 1, len(geometry)):
        if cumulative_dist[i] < end_dist:
            result.append(geometry[i])
        else:
            break

    # Add interpolated end point
    for i in range(len(cumulative_dist) - 1):
        if cumulative_dist[i] <= end_dist <= cumulative_dist[i + 1]:
            segment_dist = cumulative_dist[i + 1] - cumulative_dist[i]
            if segment_dist > 0:
                t = (end_dist - cumulative_dist[i]) / segment_dist
                p1 = geometry[i]
                p2 = geometry[i + 1]
                interp_lon = p1[0] + t * (p2[0] - p1[0])
                interp_lat = p1[1] + t * (p2[1] - p1[1])
                result.append((interp_lon, interp_lat))
            else:
                result.append(geometry[i])
            break

    return result if result else [geometry[0]]


def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> float:
    """
    Calculate haversine distance between two points in meters.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates

    Returns:
        Distance in meters
    """
    R = 6371000  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_turn_angle(bearing1: float, bearing2: float) -> float:
    """
    Calculate turn angle between two bearings.

    Args:
        bearing1: Initial bearing (0-360°)
        bearing2: Final bearing (0-360°)

    Returns:
        Turn angle in degrees (-180 to 180)
        Positive = right turn, Negative = left turn

    Example:
        >>> calculate_turn_angle(0, 90)   # Right turn
        90.0
        >>> calculate_turn_angle(0, 270)  # Left turn (shorter)
        -90.0
    """
    diff = bearing2 - bearing1

    # Normalize to -180..180
    while diff > 180:
        diff -= 360
    while diff < -180:
        diff += 360

    return diff


def get_turn_penalty(
    prev_bearing: Optional[float],
    curr_bearing: float,
    is_oneway: bool
) -> float:
    """
    Calculate time penalty for turn between edges.

    Args:
        prev_bearing: Previous edge bearing (None for start)
        curr_bearing: Current edge bearing
        is_oneway: Whether current edge is one-way

    Returns:
        Time penalty in seconds

    Turn types:
    - Straight (0-30°): 0s
    - Turn (30-90°): 5s
    - Sharp turn (90-150°): 15s
    - U-turn (150-180°): 30s (inf if oneway)
    """
    if prev_bearing is None:
        return 0.0

    angle = abs(calculate_turn_angle(prev_bearing, curr_bearing))

    if angle < 30:
        return 0.0
    elif angle < 90:
        return 5.0
    elif angle < 150:
        return 15.0
    else:
        # U-turn
        if is_oneway:
            return float('inf')  # Impossible
        return 30.0
