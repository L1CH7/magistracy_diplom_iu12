"""
pgRouting-based implementation of RoutingEngine.
Uses pgr_dijkstra for shortest path, pgr_KSP for k-shortest paths.
"""

from typing import List, Optional, Tuple, Dict, Any
import asyncpg
from loguru import logger

from .interface import (
    RoutingEngine, 
    Route, 
    RouteNotFoundError, 
    RoutingAlgorithm
)


class PgRoutingEngine(RoutingEngine):
    """
    Routing engine using pgRouting extension in PostgreSQL.
    
    Uses graphs.edges table with columns:
    - id: edge identifier
    - source: start node id
    - target: end node id
    - cost: travel time in seconds (computed from effective_speed_kmh)
    - reverse_cost: -1 for oneway, same as cost for bidirectional
    - length_m: edge length in meters
    - geometry: linestring geometry
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize engine with configuration.
        
        Args:
            config: Configuration dict with keys:
                - database: {host, port, name, user, password}
                - connection_pool: {min_size, max_size} (optional)
                - routing: {snap_radius_m} (optional)
        """
        self.config = config
        self.db_pool: Optional[asyncpg.Pool] = None
        self.snap_radius_m = config.get('routing', {}).get('snap_radius_m', 100.0)
        logger.info("PgRoutingEngine initialized with config: {}", config.keys())
    
    async def initialize(self) -> None:
        """
        Setup database connection pool and verify pgRouting extension.
        """
        db_config = self.config['database']
        pool_config = self.config.get('connection_pool', {})
        
        try:
            self.db_pool = await asyncpg.create_pool(
                host=db_config['host'],
                port=db_config['port'],
                database=db_config['name'],
                user=db_config['user'],
                password=db_config['password'],
                min_size=pool_config.get('min_size', 2),
                max_size=pool_config.get('max_size', 10),
                command_timeout=60
            )
            logger.info("Database connection pool created (min={}, max={})", 
                       pool_config.get('min_size', 2), 
                       pool_config.get('max_size', 10))
            
            # Verify pgRouting extension
            async with self.db_pool.acquire() as conn:
                version = await conn.fetchval(
                    "SELECT extversion FROM pg_extension WHERE extname = 'pgrouting'"
                )
                if not version:
                    raise RuntimeError("pgRouting extension not found in database")
                logger.info("pgRouting extension version: {}", version)
                
        except Exception as e:
            logger.error("Failed to initialize PgRoutingEngine: {}", e)
            if self.db_pool:
                await self.db_pool.close()
                self.db_pool = None
            raise
    
    async def find_route(
        self, 
        start_node: int, 
        end_node: int, 
        priority: int = 0
    ) -> Route:
        """
        Find shortest path using pgr_dijkstra.
        
        Args:
            start_node: Starting node id
            end_node: Target node id
            priority: Agent priority (0=regular, 1=taxi, 2=emergency) - not yet used
        
        Returns:
            Route with edge_ids, total_cost, total_distance_m
        
        Raises:
            RouteNotFoundError: If no path exists
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        async with self.db_pool.acquire() as conn:
            # Use pgr_dijkstra with graphs.edges
            query = """
                SELECT 
                    array_agg(edge ORDER BY seq) FILTER (WHERE edge > 0) as edges,
                    max(agg_cost) as total_cost
                FROM pgr_dijkstra(
                    'SELECT id, source, target, cost, reverse_cost FROM graphs.edges_pgrouting',
                    $1, $2, 
                    directed := true
                )
            """
            
            try:
                result = await conn.fetchrow(query, start_node, end_node)
                
                if not result or not result['edges']:
                    raise RouteNotFoundError(
                        f"No route found from node {start_node} to node {end_node}"
                    )
                
                edge_ids = list(result['edges'])
                total_cost = float(result['total_cost'])
                
                # Get total distance by summing length_m of edges
                dist_result = await conn.fetchrow(
                    "SELECT SUM(length_m) as total_dist FROM graphs.edges WHERE id = ANY($1)",
                    edge_ids
                )
                total_distance = float(dist_result['total_dist'] or 0.0)
                
                logger.debug(
                    "Route found: {} edges, {:.1f}m, {:.1f}s", 
                    len(edge_ids), total_distance, total_cost
                )
                
                return Route(
                    edge_ids=edge_ids,
                    total_cost=total_cost,
                    total_distance_m=total_distance,
                    algorithm=RoutingAlgorithm.PGROUTING.value
                )
                
            except asyncpg.PostgresError as e:
                logger.error("pgr_dijkstra query failed: {}", e)
                raise RouteNotFoundError(f"Routing query failed: {e}")
    
    async def find_k_routes(
        self,
        start_node: int,
        end_node: int,
        k: int = 3,
        priority: int = 0,
        use_diversity: bool = False
    ) -> List[Route]:
        """
        Find K shortest paths using pgr_KSP (Yen's algorithm).
        
        Args:
            start_node: Starting node id
            end_node: Target node id
            k: Number of alternative routes to find
            priority: Agent priority (not yet used)
            use_diversity: If True, filter routes by diversity criteria
        
        Returns:
            List of up to k Route objects, sorted by cost
        
        Raises:
            RouteNotFoundError: If no paths exist
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        # Fetch more routes if diversity filtering enabled
        fetch_k = k * 2 if use_diversity else k
        
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT
                    path_id,
                    array_agg(edge ORDER BY seq) FILTER (WHERE edge > 0)
                      as edges,
                    array_agg(node ORDER BY seq) as nodes,
                    max(agg_cost) as cost
                FROM pgr_KSP(
                    'SELECT id, source, target, cost, reverse_cost
                     FROM graphs.edges',
                    $1::bigint, $2::bigint, $3::integer,
                    directed := true
                )
                GROUP BY path_id
                ORDER BY cost
            """

            try:
                results = await conn.fetch(
                    query, start_node, end_node, fetch_k
                )
                logger.debug(
                    f"pgr_KSP returned {len(results)} paths "
                    f"(fetch_k={fetch_k})"
                )

                if not results:
                    raise RouteNotFoundError(
                        f"No routes found from node {start_node} to node {end_node}"
                    )
                
                # Convert to Route objects
                routes = []
                for row in results:
                    edge_ids = list(row['edges'])
                    node_sequence = list(row['nodes'])
                    total_cost = float(row['cost'])
                    
                    # Get distance
                    dist_result = await conn.fetchrow(
                        "SELECT SUM(length_m) as total_dist FROM graphs.edges WHERE id = ANY($1)",
                        edge_ids
                    )
                    total_distance = float(dist_result['total_dist'] or 0.0)
                    
                    routes.append(Route(
                        edge_ids=edge_ids,
                        total_cost=total_cost,
                        total_distance_m=total_distance,
                        algorithm=RoutingAlgorithm.PGROUTING.value,
                        node_sequence=node_sequence
                    ))
                
                # Apply diversity filtering if requested
                if use_diversity and len(routes) > k:
                    routes = self._filter_by_diversity(routes, k)
                
                final_routes = routes[:k]
                logger.debug(
                    "Found {} routes (requested {}, use_diversity={})", 
                    len(final_routes), k, use_diversity
                )
                
                return final_routes
                
            except asyncpg.PostgresError as e:
                logger.error("pgr_KSP query failed: {}", e)
                raise RouteNotFoundError(f"K-routes query failed: {e}")
    
    def _filter_by_diversity(self, routes: List[Route], k: int) -> List[Route]:
        """
        Filter routes by diversity criteria.
        
        Criteria (from architecture plan):
        - space_threshold: 60% unique edges
        - divergence_point: 20-80% of route length
        - max_cost_ratio: 1.5x of shortest route
        
        Args:
            routes: List of routes sorted by cost
            k: Number of diverse routes to return
        
        Returns:
            Up to k diverse routes
        """
        if not routes:
            return []
        
        diverse_routes = [routes[0]]  # Always include shortest route
        shortest_cost = routes[0].total_cost
        
        for route in routes[1:]:
            if len(diverse_routes) >= k:
                break
            
            # Cost ratio check
            if route.total_cost > shortest_cost * 1.5:
                continue
            
            # Check diversity with each already selected route
            is_diverse = True
            for selected in diverse_routes:
                overlap = self._calculate_edge_overlap(
                    route.edge_ids, selected.edge_ids
                )
                # 65% overlap threshold (35% unique edges minimum)
                if overlap > 0.65:
                    is_diverse = False
                    logger.debug(
                        f"Route rejected: overlap {overlap:.2f} > 0.6"
                    )
                    break
            
            if is_diverse:
                diverse_routes.append(route)
                logger.debug(
                    f"Route accepted: {len(route.edge_ids)} edges, "
                    f"cost {route.total_cost:.1f}s"
                )
        
        return diverse_routes
    
    @staticmethod
    def _calculate_edge_overlap(edges1: List[int], edges2: List[int]) -> float:
        """
        Calculate edge overlap ratio between two routes.
        
        Returns:
            Overlap ratio (0.0 to 1.0), where 0.0 = no common edges, 1.0 = identical
        """
        set1 = set(edges1)
        set2 = set(edges2)
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
    
    async def snap_to_road(
        self, 
        lat: float, 
        lon: float, 
        snap_radius_m: Optional[float] = None
    ) -> Optional[Tuple[int, float]]:
        """
        Map GPS coordinates to nearest road edge (map matching).
        
        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            snap_radius_m: Search radius in meters (default from config)
        
        Returns:
            Tuple of (edge_id, position_meters) or None if no edge within radius
            position_meters: Distance along edge from start (0.0 to length_m)
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        radius = snap_radius_m if snap_radius_m is not None else self.snap_radius_m
        
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT
                    e.id as edge_id,
                    e.length_m,
                    ST_LineLocatePoint(e.geom, u.user_point) as position_frac,
                    ST_Distance(
                        ST_Transform(e.geom, 3857),
                        ST_Transform(u.user_point, 3857)
                    ) as distance_m
                FROM graphs.edges e,
                     (SELECT ST_SetSRID(ST_MakePoint($2, $1), 4326)
                      as user_point) u
                WHERE ST_DWithin(
                    ST_Transform(e.geom, 3857),
                    ST_Transform(u.user_point, 3857),
                    $3
                )
                ORDER BY distance_m
                LIMIT 1
            """
            
            result = await conn.fetchrow(query, lat, lon, radius)
            
            if result:
                edge_id = result['edge_id']
                position_meters = result['position_frac'] * result['length_m']
                logger.debug(
                    "Snapped ({:.6f}, {:.6f}) to edge {} at {:.1f}m (distance {:.1f}m)",
                    lat, lon, edge_id, position_meters, result['distance_m']
                )
                return (edge_id, position_meters)
            
            logger.debug(
                "No edge found within {:.0f}m of ({:.6f}, {:.6f})",
                radius, lat, lon
            )
            return None
    
    async def snap_to_node(
        self,
        lat: float,
        lon: float,
        snap_radius_m: Optional[float] = None
    ) -> Optional[Tuple[int, float]]:
        """
        Map GPS coordinates to nearest graph node.

        Args:
            lat: Latitude (WGS84)
            lon: Longitude (WGS84)
            snap_radius_m: Search radius in meters (default from config)

        Returns:
            Tuple of (node_id, distance_m) or None if no node within radius
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")

        radius = (
            snap_radius_m if snap_radius_m is not None
            else self.snap_radius_m
        )

        async with self.db_pool.acquire() as conn:
            query = """
                SELECT
                    n.id as node_id,
                    ST_Distance(
                        ST_Transform(n.geom, 3857),
                        ST_Transform(
                            ST_SetSRID(ST_MakePoint($2, $1), 4326),
                            3857
                        )
                    ) as distance_m
                FROM graphs.nodes n
                WHERE ST_DWithin(
                    ST_Transform(n.geom, 3857),
                    ST_Transform(
                        ST_SetSRID(ST_MakePoint($2, $1), 4326),
                        3857
                    ),
                    $3
                )
                ORDER BY distance_m
                LIMIT 1
            """

            result = await conn.fetchrow(query, lat, lon, radius)

            if result:
                node_id = result['node_id']
                distance = result['distance_m']
                logger.debug(
                    "Snapped ({:.6f}, {:.6f}) to node {} (dist {:.1f}m)",
                    lat, lon, node_id, distance
                )
                return (node_id, distance)

            logger.debug(
                "No node found within {:.0f}m of ({:.6f}, {:.6f})",
                radius, lat, lon
            )
            return None
    
    async def update_edge_load(self, edge_id: int, new_load: int) -> None:
        """
        Update traffic load on an edge.
        
        Updates graphs.edges.current_load which affects effective_speed_kmh
        (computed column using BPR congestion function).
        
        Args:
            edge_id: Edge identifier
            new_load: Number of agents currently on this edge
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE graphs.edges SET current_load = $1 WHERE id = $2",
                new_load, edge_id
            )
    
    async def get_graph_stats(self) -> Dict[str, Any]:
        """
        Get graph statistics for monitoring.
        
        Returns:
            Dict with keys:
                - total_nodes: Number of nodes
                - total_edges: Number of edges
                - total_turn_restrictions: Number of turn restrictions
                - avg_edge_length_m: Average edge length
                - total_network_length_km: Total network length
        """
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        async with self.db_pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    (SELECT COUNT(*) FROM graphs.nodes) as total_nodes,
                    (SELECT COUNT(*) FROM graphs.edges) as total_edges,
                    (SELECT COUNT(*) FROM graphs.turn_restrictions) as total_turn_restrictions,
                    (SELECT AVG(length_m) FROM graphs.edges) as avg_edge_length_m,
                    (SELECT SUM(length_m) / 1000.0 FROM graphs.edges) as total_network_length_km
            """)
            
            return {
                'total_nodes': stats['total_nodes'],
                'total_edges': stats['total_edges'],
                'total_turn_restrictions': stats['total_turn_restrictions'],
                'avg_edge_length_m': float(stats['avg_edge_length_m'] or 0.0),
                'total_network_length_km': float(stats['total_network_length_km'] or 0.0)
            }
    
    async def close(self) -> None:
        """
        Close database connection pool and cleanup resources.
        """
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
            logger.info("PgRoutingEngine closed")
