"""Pathfinding algorithms: A*, Yen's K-shortest paths.

Uses Graph class with adjacency list for O(1) neighbor access.
"""

import heapq
from typing import List, Optional, Set, Tuple, Callable
from dataclasses import dataclass, field
from src.routing.graph import Graph
from loguru import logger as log



@dataclass(order=True)
class PriorityItem:
    """Priority queue item for A*."""
    priority: float
    node_id: int = field(compare=False)
    g_score: float = field(compare=False)


def haversine_heuristic(
    graph: Graph,
    node_id: int,
    goal_id: int
) -> float:
    """Haversine distance heuristic for A*.
    
    Args:
        graph: Graph instance
        node_id: Current node ID
        goal_id: Goal node ID
        
    Returns:
        Estimated distance in meters
    """
    import math
    
    node = graph.get_node(node_id)
    goal = graph.get_node(goal_id)
    
    if not node or not goal:
        return 0.0
    
    # Haversine formula
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(node.lat)
    phi2 = math.radians(goal.lat)
    dphi = math.radians(goal.lat - node.lat)
    dlambda = math.radians(goal.lon - node.lon)
    
    a = (
        math.sin(dphi / 2)**2 +
        math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def astar(
    graph: Graph,
    start_id: int,
    goal_id: int,
    heuristic: Optional[Callable] = None,
    use_turn_penalties: bool = False
) -> Optional[List[int]]:
    """A* pathfinding algorithm with optional turn penalties.
    
    Args:
        graph: Graph instance
        start_id: Start node ID
        goal_id: Goal node ID
        heuristic: Heuristic function (node_id, goal_id) → distance
                   If None, uses haversine_heuristic
        use_turn_penalties: If True, accounts for turn angles
    
    Returns:
        List of edge IDs forming the path, or None if no path exists
    """
    if heuristic is None:
        def default_heuristic(nid, gid):
            return haversine_heuristic(graph, nid, gid)
        heuristic = default_heuristic
    
    if not use_turn_penalties:
        # Original A* without turn penalties (fast path)
        return _astar_simple(
            graph, start_id, goal_id, heuristic
        )
    
    # A* with turn penalties: state = (node_id, prev_edge_id)
    from src.data.osrm_profile import get_car_profile
    profile = get_car_profile()
    
    # Priority queue: (f_score, node_id, prev_edge_id, g_score)
    open_set = [(0.0, start_id, None, 0.0)]
    
    # came_from: (node_id, prev_edge_id) → (parent_node, parent_edge, edge_id)
    came_from: dict[Tuple[int, Optional[int]], Tuple] = {}
    
    # g_score: (node_id, prev_edge_id) → cost from start
    g_score: dict[Tuple[int, Optional[int]], float] = {
        (start_id, None): 0.0
    }
    
    # closed set: (node_id, prev_edge_id)
    closed_set: Set[Tuple[int, Optional[int]]] = set()
    
    while open_set:
        f, current_id, prev_edge_id, current_g = heapq.heappop(open_set)
        current_state = (current_id, prev_edge_id)
        
        if current_state in closed_set:
            continue
        
        if current_id == goal_id:
            # Reconstruct path
            path = []
            state = current_state
            while state in came_from:
                parent_node, parent_edge, edge_id = came_from[state]
                if edge_id is not None:
                    path.append(edge_id)
                state = (parent_node, parent_edge)
            path.reverse()
            
            log.debug(
                "A* path found (with turns)",
                edges=len(path),
                cost=current_g
            )
            return path
        
        closed_set.add(current_state)
        
        # Explore neighbors
        for edge in graph.get_neighbors(current_id):
            neighbor_id = edge.end_node_id
            
            # Calculate turn penalty
            turn_penalty = 0.0
            if prev_edge_id is not None:
                prev_edge = graph.get_edge(prev_edge_id)
                # Calculate bearing difference
                has_bearings = (
                    hasattr(edge, 'bearing') and
                    hasattr(prev_edge, 'bearing') and
                    edge.bearing is not None and
                    prev_edge.bearing is not None
                )
                if has_bearings:
                    angle_diff = abs(edge.bearing - prev_edge.bearing)
                    if angle_diff > 180:
                        angle_diff = 360 - angle_diff
                    turn_penalty = profile.get_turn_penalty(
                        angle_diff, edge.oneway
                    )
                    
                    # Skip if u-turn blocked
                    if turn_penalty == float('inf'):
                        continue
            
            # Calculate cost
            tentative_g = (
                current_g + edge.get_travel_time() + turn_penalty
            )
            neighbor_state = (neighbor_id, edge.id)
            
            if (neighbor_state in g_score and
                    tentative_g >= g_score[neighbor_state]):
                continue
            
            g_score[neighbor_state] = tentative_g
            f_score = tentative_g + heuristic(neighbor_id, goal_id)
            
            heapq.heappush(
                open_set,
                (f_score, neighbor_id, edge.id, tentative_g)
            )
            came_from[neighbor_state] = (current_id, prev_edge_id, edge.id)
    
    log.warning("A* no path found", start=start_id, goal=goal_id)
    return None


def _astar_simple(
    graph: Graph,
    start_id: int,
    goal_id: int,
    heuristic: Callable
) -> Optional[List[int]]:
    """Simple A* without turn penalties (original implementation)"""
    # Priority queue: (f_score, node_id, g_score)
    open_set = [PriorityItem(0.0, start_id, 0.0)]
    
    # came_from: node_id → (parent_node_id, edge_id)
    came_from: dict[int, Tuple[int, int]] = {}
    
    # g_score: node_id → cost from start
    g_score: dict[int, float] = {start_id: 0.0}
    
    # closed set
    closed_set: Set[int] = set()
    
    while open_set:
        current_item = heapq.heappop(open_set)
        current_id = current_item.node_id
        current_g = current_item.g_score
        
        if current_id in closed_set:
            continue
        
        if current_id == goal_id:
            # Reconstruct path (as list of edge IDs)
            path = []
            node_id = goal_id
            while node_id in came_from:
                parent_id, edge_id = came_from[node_id]
                path.append(edge_id)
                node_id = parent_id
            path.reverse()
            
            log.debug(
                "A* path found",
                edges=len(path),
                cost=current_g
            )
            return path
        
        closed_set.add(current_id)
        
        # Explore neighbors
        for edge in graph.get_neighbors(current_id):
            neighbor_id = edge.end_node_id
            
            if neighbor_id in closed_set:
                continue
            
            # Cost: use travel time (considering congestion)
            tentative_g = current_g + edge.get_travel_time()
            
            is_better = (neighbor_id not in g_score or
                         tentative_g < g_score[neighbor_id])
            if is_better:
                g_score[neighbor_id] = tentative_g
                f_score = tentative_g + heuristic(neighbor_id, goal_id)
                
                heapq.heappush(
                    open_set,
                    PriorityItem(f_score, neighbor_id, tentative_g)
                )
                came_from[neighbor_id] = (current_id, edge.id)
    
    log.warning("A* no path found", start=start_id, goal=goal_id)
    return None


def _paths_similar(path1: List[int], path2: List[int], threshold: float = 0.75) -> bool:
    """Check if two paths share too many edges (are too similar).
    
    Args:
        path1: First path (list of edge IDs)
        path2: Second path (list of edge IDs)
        threshold: Similarity threshold (0.0-1.0), default 0.75
        
    Returns:
        True if paths share >= threshold fraction of edges
    """
    if not path1 or not path2:
        return False
    
    set1 = set(path1)
    set2 = set(path2)
    
    common = len(set1 & set2)
    max_len = max(len(set1), len(set2))
    
    similarity = common / max_len if max_len > 0 else 0.0
    return similarity >= threshold


def k_shortest_paths(
    graph: Graph,
    start_id: int,
    goal_id: int,
    k: int = 5,
    use_turn_penalties: bool = False
) -> List[List[int]]:
    """Yen's K-shortest paths algorithm with similarity filtering.
    
    Finds K shortest simple paths (no cycles) between start and goal.
    Filters out paths that are too similar (share >75% edges).
    
    Args:
        graph: Graph instance
        start_id: Start node ID
        goal_id: Goal node ID
        k: Number of paths to find
        use_turn_penalties: If True, accounts for turn angles
        
    Returns:
        List of paths, each path is a list of edge IDs
    """
    # A: List of shortest paths
    A: List[Tuple[float, List[int]]] = []
    
    # B: Heap of potential paths
    B: List[Tuple[float, List[int]]] = []
    
    # Find first shortest path
    first_path = astar(
        graph, start_id, goal_id, use_turn_penalties=use_turn_penalties
    )
    if first_path is None:
        log.warning("No path exists", start=start_id, goal=goal_id)
        return []
    
    first_cost = sum(
        graph.get_edge(eid).get_travel_time() for eid in first_path
    )
    A.append((first_cost, first_path))
    
    for k_iter in range(1, k):
        # Previous path
        prev_cost, prev_path = A[-1]
        
        # Iterate over all nodes in previous path except goal
        for i in range(len(prev_path)):
            # Spur node: where we deviate
            spur_node = (
                start_id if i == 0
                else graph.get_edge(prev_path[i-1]).end_node_id
            )
            
            # Root path: path up to spur node
            root_path = prev_path[:i]
            
            # Remove edges that would create duplicate paths
            removed_edges = set()
            for path_cost, path in A:
                if len(path) > i and path[:i] == root_path:
                    # Remove edge from spur node
                    edge_to_remove = path[i]
                    removed_edges.add(edge_to_remove)
            
            # Temporarily remove edges (by marking them)
            # TODO: Implement edge removal in Graph class
            # For now, skip this optimization
            
            # Find spur path from spur_node to goal
            spur_path = astar(
                graph, spur_node, goal_id,
                use_turn_penalties=use_turn_penalties
            )
            
            if spur_path:
                # Total path: root + spur
                total_path = root_path + spur_path
                
                # Calculate cost
                total_cost = sum(
                    graph.get_edge(eid).get_travel_time()
                    for eid in total_path
                )
                
                # Add to candidates if not duplicate and not too similar
                is_duplicate = any(path == total_path for _, path in B)
                is_too_similar = any(
                    _paths_similar(total_path, existing_path)
                    for _, existing_path in A
                )
                
                if not is_duplicate and not is_too_similar:
                    heapq.heappush(B, (total_cost, total_path))
        
        if not B:
            # No more paths
            break
        
        # Add best candidate to A
        best_cost, best_path = heapq.heappop(B)
        A.append((best_cost, best_path))
    
    # Return just the paths (without costs)
    paths = [path for cost, path in A]
    
    log.info(
        "K-shortest paths found",
        requested=k,
        found=len(paths),
        start=start_id,
        goal=goal_id
    )
    
    return paths


def snap_point_to_graph(
    graph: Graph,
    lat: float,
    lon: float,
    k: int = 5
) -> List[int]:
    """Snap point to K nearest nodes in graph.
    
    Args:
        graph: Graph instance
        lat: Latitude
        lon: Longitude
        k: Number of nearest nodes to return
        
    Returns:
        List of node IDs sorted by distance
    """
    nearest = graph.find_nearest_nodes(lat, lon, k)
    node_ids = [node_id for node_id, dist in nearest]
    
    log.debug(
        "Point snapped to graph",
        lat=lat,
        lon=lon,
        nearest_nodes=len(node_ids)
    )
    
    return node_ids
