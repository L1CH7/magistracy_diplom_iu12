"""
A* + Yen routing engine implementation.

Uses existing src/routing/ modules.
"""

import os
import sys
from typing import List, Tuple
from loguru import logger

# Add project root to path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
)

from .engine import RouteEngine, Route, RouteSegment  # noqa: E402
from src.routing.graph import Graph  # noqa: E402
from src.routing.pathfinding import (  # noqa: E402
    k_shortest_paths, snap_point_to_graph
)
from src.data.postgis_manager import PostGISManager  # noqa: E402


class AStarEngine(RouteEngine):
    """
    A* + Yen routing engine.
    
    Uses custom Python implementation from src/routing/:
    - graph.py: Graph class with adjacency list
    - pathfinding.py: A* + Yen's K-shortest paths
    - snap_to_edge.py: PostGIS-based snapping
    """
    
    def __init__(self, config: dict):
        """
        Initialize A* engine.
        
        Args:
            config: Router configuration dict
        """
        self.config = config
        self.db: PostGISManager | None = None
        self.graph: Graph | None = None
        
        # Extract config values
        self.use_turn_penalties = (
            config.get("algorithms", {})
            .get("astar", {})
            .get("use_turn_penalties", True)
        )
        
        self.diversity_threshold = (
            config.get("routing", {})
            .get("diversity", {})
            .get("similarity_threshold", 0.75)
        )
        
        logger.info(
            "AStarEngine initialized",
            turn_penalties=self.use_turn_penalties,
            diversity_threshold=self.diversity_threshold
        )
    
    async def initialize(self):
        """Load graph from database."""
        logger.info("AStarEngine: Loading graph from database...")
        
        try:
            # Initialize PostGIS manager
            self.db = PostGISManager()
            logger.debug("AStarEngine: PostGIS manager initialized")
            
            # Load graph (blocking operation, ~500ms)
            self.graph = Graph.load_from_db(self.db)
            
            logger.success(
                "AStarEngine: Graph loaded",
                nodes=len(self.graph.nodes),
                edges=len(self.graph.edges)
            )
        except Exception as e:
            logger.error(f"AStarEngine: Failed to load graph: {e}")
            raise
    
    async def shutdown(self):
        """Cleanup resources."""
        if self.db:
            self.db.close()
        
        logger.info("AStarEngine shutdown complete")
    
    async def calculate_routes(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        k: int = 3,
        agent_mode: str = "normal",
        priority: int = 0
    ) -> List[Route]:
        """
        Calculate K alternative routes using A* + Yen.
        
        Steps:
        1. Snap start/end points to nearest nodes
        2. Call k_shortest_paths() from src/routing/pathfinding.py
        3. Filter by diversity (similarity_threshold)
        4. Build Route objects with segments
        """
        if not self.graph:
            raise RuntimeError("Graph not loaded. Call initialize() first.")
        
        # Get config values
        snap_k = (
            self.config.get("routing", {})
            .get("snap", {})
            .get("k_nearest", 5)
        )
        
        # Step 1: Snap to nearest nodes
        start_nodes = snap_point_to_graph(
            self.graph, start_lat, start_lon, k=snap_k
        )
        end_nodes = snap_point_to_graph(
            self.graph, end_lat, end_lon, k=snap_k
        )
        
        if not start_nodes or not end_nodes:
            logger.warning(
                "No nodes found near points",
                start=(start_lat, start_lon),
                end=(end_lat, end_lon)
            )
            return []
        
        # Use closest nodes
        start_node = start_nodes[0]
        end_node = end_nodes[0]
        
        logger.info(
            f"AStarEngine: Routing node {start_node} → {end_node}",
            k=k,
            agent_mode=agent_mode,
            priority=priority
        )
        logger.trace(
            f"AStarEngine: Snapped start to {len(start_nodes)} nodes, "
            f"end to {len(end_nodes)} nodes"
        )
        
        # Step 2: K-shortest paths
        logger.debug(
            "AStarEngine: Running k_shortest_paths",
            turn_penalties=self.use_turn_penalties
        )
        paths = k_shortest_paths(
            self.graph,
            start_node,
            end_node,
            k=k,
            use_turn_penalties=self.use_turn_penalties
        )
        
        if not paths:
            logger.warning("AStarEngine: No paths found")
            return []
        
        logger.debug(f"AStarEngine: Found {len(paths)} raw paths")
        
        # Step 3: Build Route objects
        routes = []
        for route_id, edge_ids in enumerate(paths):
            segments = []
            total_distance = 0.0
            total_time = 0.0
            
            for edge_id in edge_ids:
                edge = self.graph.get_edge(edge_id)
                if not edge:
                    continue
                
                segment = RouteSegment(
                    edge_id=edge.id,
                    from_node=edge.start_node_id,
                    to_node=edge.end_node_id,
                    distance_m=edge.length_m,
                    time_sec=edge.get_travel_time(),
                    speed_limit_kmh=edge.speed_limit_kmh,
                    effective_speed_kmh=(
                        edge.effective_speed_kmh or edge.speed_limit_kmh
                    ),
                    bearing=edge.bearing
                )
                
                segments.append(segment)
                total_distance += segment.distance_m
                total_time += segment.time_sec
            
            # Calculate diversity (shared edges with route 0)
            diversity = 0.0
            if route_id > 0 and routes:
                first_route_edges = set(routes[0].edge_ids)
                current_edges = set(edge_ids)
                shared = len(first_route_edges & current_edges)
                diversity = 1.0 - (shared / len(current_edges))
            
            route = Route(
                route_id=route_id,
                segments=segments,
                total_distance_m=total_distance,
                estimated_time_sec=total_time,
                diversity_score=diversity,
                edge_ids=edge_ids
            )
            
            routes.append(route)
            
            logger.trace(
                f"AStarEngine: Route {route_id}",
                distance_m=round(total_distance, 1),
                time_sec=round(total_time, 1),
                diversity=round(diversity, 2),
                edges=len(edge_ids)
            )
        
        logger.info(
            f"AStarEngine: Built {len(routes)} routes",
            avg_distance=round(
                sum(r.total_distance_m for r in routes) / len(routes), 1
            ),
            avg_time=round(
                sum(r.estimated_time_sec for r in routes) / len(routes), 1
            )
        )
        
        return routes
    
    async def snap_to_road(
        self,
        lat: float,
        lon: float,
        k: int = 5,
        max_distance_m: float = 100.0
    ) -> List[Tuple[int, float]]:
        """
        Snap point to nearest road edges.
        
        Uses src/routing/snap_to_edge.py PostGIS-based snapping.
        """
        if not self.graph or not self.db:
            raise RuntimeError("Engine not initialized")
        
        from src.routing.snap_to_edge import snap_point_to_edges
        
        snaps = snap_point_to_edges(
            self.db, lat, lon, k=k, max_distance_m=max_distance_m
        )
        
        return [(snap.edge_id, snap.distance_m) for snap in snaps]
