"""
Route builder module for multi-point routing with via points.

This module provides functionality to build K-best routes through multiple
points (from → via → ... → to) using K-shortest paths between consecutive
point pairs.

Author: bmstu/diplom
"""

from typing import List, Tuple
from dataclasses import dataclass, field

from src.routing.graph import Graph
from src.routing.pathfinding import k_shortest_paths, snap_point_to_graph
from src.utils.logger import setup_logger


log = setup_logger(__name__)


@dataclass
class RouteSegment:
    """Represents a segment between two consecutive via points."""
    from_point_idx: int
    to_point_idx: int
    from_node_id: int
    to_node_id: int
    edge_ids: List[int]
    distance_m: float
    time_sec: float

    def __repr__(self) -> str:
        return (f"RouteSegment(p{self.from_point_idx}→p{self.to_point_idx}, "
                f"n{self.from_node_id}→n{self.to_node_id}, "
                f"{len(self.edge_ids)} edges, "
                f"{self.distance_m:.1f}m, {self.time_sec:.1f}s)")


@dataclass
class Route:
    """Complete route from start to finish through via points."""
    id: int
    segments: List[RouteSegment]
    total_distance_m: float
    total_time_sec: float
    edge_ids: List[int] = field(default_factory=list)
    geometry: List[Tuple[float, float]] = field(default_factory=list)

    def __repr__(self) -> str:
        return (f"Route(id={self.id}, "
                f"{len(self.segments)} segments, "
                f"{len(self.edge_ids)} edges, "
                f"{self.total_distance_m:.1f}m, "
                f"{self.total_time_sec:.1f}s)")


def _calculate_segment_metrics(
    graph: Graph,
    edge_ids: List[int]
) -> Tuple[float, float]:
    """
    Calculate distance and time for a segment.

    Args:
        graph: Graph instance
        edge_ids: List of edge IDs in the segment

    Returns:
        Tuple of (distance_m, time_sec)
    """
    distance = 0.0
    time = 0.0

    for edge_id in edge_ids:
        edge = graph.get_edge(edge_id)
        if edge:
            distance += edge.length_m
            time += edge.get_travel_time()

    return distance, time


def _snap_points_to_nodes(
    graph: Graph,
    points: List[Tuple[float, float]],
    k: int = 5
) -> List[List[int]]:
    """
    Snap each point to K nearest nodes.

    Args:
        graph: Graph instance
        points: List of (lat, lon) tuples
        k: Number of nearest nodes to return per point

    Returns:
        List of lists, where each inner list contains K nearest node IDs
    """
    snapped = []
    for idx, (lat, lon) in enumerate(points):
        nearest = snap_point_to_graph(graph, lat, lon, k=k)
        log.debug("Snapped point",
                  point_idx=idx,
                  lat=lat,
                  lon=lon,
                  nearest_nodes=nearest)
        snapped.append(nearest)

    return snapped


def _find_k_paths_between_nodes(
    graph: Graph,
    from_nodes: List[int],
    to_nodes: List[int],
    k: int
) -> List[Tuple[int, int, List[int], float, float]]:
    """
    Find K shortest paths between sets of from/to nodes.

    Tries all combinations of from_nodes × to_nodes and returns
    top K paths sorted by travel time.

    Args:
        graph: Graph instance
        from_nodes: List of candidate start node IDs
        to_nodes: List of candidate end node IDs
        k: Number of best paths to return

    Returns:
        List of tuples: (from_node_id, to_node_id, edge_ids, dist, time)
        Sorted by time (best first)
    """
    candidates = []

    for from_node in from_nodes:
        for to_node in to_nodes:
            if from_node == to_node:
                continue

            paths = k_shortest_paths(
                graph, from_node, to_node, k=k,
                use_turn_penalties=True
            )

            for path_edges in paths:
                if not path_edges:
                    continue

                distance, time = _calculate_segment_metrics(graph, path_edges)
                candidates.append((from_node, to_node, path_edges,
                                   distance, time))

    # Sort by time (best first)
    candidates.sort(key=lambda x: x[4])

    # Return top K
    return candidates[:k]


def _combine_segments_to_routes(
    all_segment_options: List[List[Tuple[int, int, List[int], float, float]]],
    k: int
) -> List[List[RouteSegment]]:
    """
    Combine segment options into K best complete routes.

    Strategy: For each segment position, try top options and combine.
    Use greedy approach: pick best segment, then best next segment, etc.

    Args:
        all_segment_options: List of segment option lists,
                             one per consecutive point pair
        k: Number of complete routes to generate

    Returns:
        List of route segment lists (one list per complete route)
    """
    if not all_segment_options:
        return []

    # Simple greedy approach for R&D-1:
    # For each of K routes, pick i-th best option from each segment
    routes = []

    for route_idx in range(k):
        segments = []
        valid = True

        for seg_idx, options in enumerate(all_segment_options):
            if route_idx >= len(options):
                # Not enough options for this segment
                valid = False
                break

            from_node, to_node, edges, dist, time = options[route_idx]
            segment = RouteSegment(
                from_point_idx=seg_idx,
                to_point_idx=seg_idx + 1,
                from_node_id=from_node,
                to_node_id=to_node,
                edge_ids=edges,
                distance_m=dist,
                time_sec=time
            )
            segments.append(segment)

        if valid and segments:
            routes.append(segments)

        if len(routes) >= k:
            break

    return routes


def _build_route_geometry(
    graph: Graph,
    edge_ids: List[int]
) -> List[Tuple[float, float]]:
    """
    Build route geometry from edge IDs.

    Args:
        graph: Graph instance
        edge_ids: List of edge IDs

    Returns:
        List of (lon, lat) coordinates
    """
    if not edge_ids:
        return []

    coords = []

    for edge_id in edge_ids:
        edge = graph.get_edge(edge_id)
        if not edge:
            continue

        # Add start node
        start_node = graph.get_node(edge.start_node_id)
        if start_node:
            coords.append((start_node.lon, start_node.lat))

    # Add last node
    last_edge = graph.get_edge(edge_ids[-1])
    if last_edge:
        end_node = graph.get_node(last_edge.end_node_id)
        if end_node:
            coords.append((end_node.lon, end_node.lat))

    return coords


def build_routes(
    graph: Graph,
    points: List[Tuple[float, float]],
    k: int = 5,
    snap_k: int = 5
) -> List[Route]:
    """
    Build K best routes through multiple points.

    Args:
        graph: Graph instance
        points: List of (lat, lon) tuples, where first=from, last=to,
                middle=via points
        k: Number of best routes to return
        snap_k: Number of nearest nodes to consider when snapping points

    Returns:
        List of Route objects, sorted by total_time_sec (best first)

    Example:
        >>> points = [(55.751, 37.618), (55.752, 37.620), (55.753, 37.622)]
        >>> routes = build_routes(graph, points, k=5)
        >>> print(routes[0])  # Best route
    """
    if len(points) < 2:
        log.error("Need at least 2 points for routing", num_points=len(points))
        return []

    log.info("Building routes",
             num_points=len(points),
             k=k,
             snap_k=snap_k)

    # Step 1: Snap all points to nearest nodes
    snapped_nodes = _snap_points_to_nodes(graph, points, k=snap_k)

    # Step 2: Find K paths between each consecutive pair
    all_segment_options = []

    for i in range(len(points) - 1):
        from_nodes = snapped_nodes[i]
        to_nodes = snapped_nodes[i + 1]

        log.debug("Finding paths for segment",
                  from_point_idx=i,
                  to_point_idx=i + 1,
                  from_nodes=from_nodes,
                  to_nodes=to_nodes)

        segment_options = _find_k_paths_between_nodes(
            graph, from_nodes, to_nodes, k
        )

        if not segment_options:
            log.warning("No paths found for segment",
                        from_point_idx=i,
                        to_point_idx=i + 1)
            return []

        all_segment_options.append(segment_options)
        log.debug("Found segment options",
                  from_point_idx=i,
                  to_point_idx=i + 1,
                  num_options=len(segment_options))

    # Step 3: Combine segments into complete routes
    route_segments = _combine_segments_to_routes(all_segment_options, k)

    if not route_segments:
        log.error("Could not combine segments into routes")
        return []

    log.info("Combined segments into routes", num_routes=len(route_segments))

    # Step 4: Build Route objects with all metadata
    routes = []

    for route_id, segments in enumerate(route_segments):
        # Flatten edge IDs
        all_edges = []
        for seg in segments:
            all_edges.extend(seg.edge_ids)

        # Calculate totals
        total_distance = sum(seg.distance_m for seg in segments)
        total_time = sum(seg.time_sec for seg in segments)

        # Build geometry
        geometry = _build_route_geometry(graph, all_edges)

        route = Route(
            id=route_id,
            segments=segments,
            total_distance_m=total_distance,
            total_time_sec=total_time,
            edge_ids=all_edges,
            geometry=geometry
        )

        routes.append(route)
        log.debug("Built route", route=route)

    # Sort by time (best first)
    routes.sort(key=lambda r: r.total_time_sec)

    # Reassign IDs after sorting
    for idx, route in enumerate(routes):
        route.id = idx

    log.info("Routes built successfully",
             num_routes=len(routes),
             best_time_sec=routes[0].total_time_sec if routes else None,
             best_distance_m=routes[0].total_distance_m if routes else None)

    return routes
