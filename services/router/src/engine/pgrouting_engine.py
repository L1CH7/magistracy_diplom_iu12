"""
pgRouting-based implementation of RoutingEngine.
"""

from typing import List, Optional, Tuple, Dict, Any
import asyncpg
from loguru import logger
import json
import shapely.wkb
import numpy as np
from shapely.geometry import mapping

from .interface import (
    RoutingEngine, 
    Route, 
    RouteNotFoundError, 
    RoutingAlgorithm
)


class PgRoutingEngine(RoutingEngine):
    """
    Routing engine using pgRouting extension in PostgreSQL.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.db_pool: Optional[asyncpg.Pool] = None
        self.snap_radius_m = config.get('routing', {}).get('snap_radius_m', 100.0)
        logger.info(f"PgRoutingEngine initialized with config keys: {list(config.keys())}")
    
    async def initialize(self) -> None:
        """
        Setup database connection pool and verify pgRouting extension.
        """
        db_cfg = self.config['database']
        dsn = f"postgresql://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['database']}"
        pool_cfg = self.config.get('connection_pool', {})
        
        self.db_pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=pool_cfg.get('min_size', 2),
            max_size=pool_cfg.get('max_size', 10)
        )
        logger.info("PgRoutingEngine: DB pool connected")

    async def find_route(self, start_node: int, end_node: int, priority: int = 0) -> Route:
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
        
        async with self.db_pool.acquire() as conn:
            # OPTIMIZATION: pgr_dijkstra + Dynamic BBOX
            # drastically reduces RAM/CPU usage for concurrent requests.
            # Switched from A* to Dijkstra to avoid expensive node joins.
            query = """
                WITH 
                start_n AS (SELECT geom FROM graphs.nodes WHERE id = $1::bigint),
                end_n AS (SELECT geom FROM graphs.nodes WHERE id = $2::bigint),
                -- 1. Calculate Dynamic BBOX (Distance * 0.5, but min ~1.5-2km buffer)
                bbox_calc AS (
                    SELECT 
                        ST_XMin(box) as minx, ST_YMin(box) as miny,
                        ST_XMax(box) as maxx, ST_YMax(box) as maxy
                    FROM (
                        SELECT ST_Expand(
                            ST_Envelope(ST_MakeLine(start_n.geom, end_n.geom)), 
                            GREATEST(0.015, ST_Distance(start_n.geom, end_n.geom) * 0.5)
                        ) as box 
                        FROM start_n, end_n
                    ) sub
                ),
                -- 2. Run Dijkstra on the subset of edges
                route AS (
                    SELECT * FROM pgr_dijkstra(
                        format(
                            'SELECT id, source_id as source, target_id as target, cost, reverse_cost
                             FROM graphs.edges
                             WHERE geometry && ST_MakeEnvelope(%%s, %%s, %%s, %%s, 4326)',
                            (SELECT minx FROM bbox_calc), (SELECT miny FROM bbox_calc),
                            (SELECT maxx FROM bbox_calc), (SELECT maxy FROM bbox_calc)
                        ),
                        $1::bigint, $2::bigint, directed := true
                    )
                ),
                -- 3. Order and fetch geometry
                ordered_path AS (
                    SELECT 
                        r1.seq, r1.node, r1.edge, r1.cost,
                        LEAD(r1.node) OVER (ORDER BY r1.seq) as next_node
                    FROM route r1
                    WHERE r1.edge > 0 OR r1.node = $2::bigint
                )
                SELECT 
                    op.seq,
                    op.node as from_node,
                    op.next_node as to_node,
                    op.edge,
                    op.cost,
                    e.length_m,
                    e.speed_limit_kmh as max_speed, 
                    -- FIXED GEOMETRY LOGIC: Source Check + WKB
                    -- If op.node == source_id, we are traversing Forward.
                    -- If op.node == target_id, we are traversing Backward (Reverse).
                    ST_AsBinary(
                        CASE 
                            WHEN op.node = e.source_id THEN e.geometry
                            ELSE ST_Reverse(e.geometry)
                        END
                    ) as geom_wkb
                FROM ordered_path op
                LEFT JOIN graphs.edges e ON op.edge = e.id
                WHERE op.edge != -1
                ORDER BY op.seq
            """
            rows = await conn.fetch(query, start_node, end_node)
            if not rows:
                raise RouteNotFoundError(f"No route from {start_node} to {end_node}")
            
            return self._rows_to_route(rows)

    def _rows_to_route(self, rows: List[Any]) -> Route:
        """Helper to convert DB result rows to Route object."""
        segments = []
        total_distance = 0.0
        total_cost = 0.0
        node_sequence = []
        
        for row in rows:
            # Handle standard rows
            dist = float(row['length_m'] or 0)
            cost = float(row['cost'] or 0) 
            
            geom = None
            if 'geom_wkb' in row and row['geom_wkb']:
                 try:
                     # Parse WKB bytes directly to Shapely object
                     g = shapely.wkb.loads(row['geom_wkb'])
                     # Convert to GeoJSON-compatible dict
                     geom = mapping(g)
                 except Exception:
                     # Fallback or log if needed, but passing None is safer than crashing
                     pass
            elif 'geometry_json' in row:
                 # Legacy fallback
                 g = row.get('geometry_json')
                 if isinstance(g, str): geom = json.loads(g)
                 else: geom = g
            
            segment = {
                "edge_id": row['edge'],
                "from_node": row.get('from_node'),
                "to_node": row.get('to_node'), # Uses the CTE LEAD value
                "distance_m": dist,
                "speed_limit": float(row.get('max_speed') or 60.0),
                "geometry_json": geom
            }
            segments.append(segment)
            node_sequence.append(row['from_node'])
            
            total_cost += cost
            total_distance += dist
            
        # Ensure final node is in sequence (from last segment's to_node)
        if segments and segments[-1]['to_node'] is not None:
             # Check if already added (avoid duplicate if rows somehow included it)
             if not node_sequence or node_sequence[-1] != segments[-1]['to_node']:
                 node_sequence.append(segments[-1]['to_node'])
        
        return Route(
            edge_ids=[s['edge_id'] for s in segments],
            total_cost=total_cost,
            total_distance_m=total_distance,
            algorithm="pgr_dijkstra",
            node_sequence=node_sequence,
            segments=segments
        )

    async def find_k_routes(self, start_node: int, end_node: int, k: int = 3, priority: int = 0, use_diversity: bool = False) -> List[Route]:
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
            
        async with self.db_pool.acquire() as conn:
            routes = []
            penalized_edges = [] 
            
            # Optimization: Use the same Dynamic BBOX query structure as find_route
            # But insert penalty logic into the SQL string.
            for _ in range(k):
                query = """
                    WITH 
                    start_n AS (SELECT geom FROM graphs.nodes WHERE id = $1::bigint),
                    end_n AS (SELECT geom FROM graphs.nodes WHERE id = $2::bigint),
                    bbox_calc AS (
                        SELECT 
                            ST_XMin(box) as minx, ST_YMin(box) as miny,
                            ST_XMax(box) as maxx, ST_YMax(box) as maxy
                        FROM (
                            SELECT ST_Expand(
                                ST_Envelope(ST_MakeLine(start_n.geom, end_n.geom)), 
                                GREATEST(0.015, ST_Distance(start_n.geom, end_n.geom) * 0.5)
                            ) as box 
                            FROM start_n, end_n
                        ) sub
                    ),
                    route AS (
                        SELECT * FROM pgr_dijkstra(
                            format(
                                'SELECT id, source_id as source, target_id as target, 
                                 CASE 
                                     WHEN id = ANY(%L::bigint[]) THEN cost * 5.0 
                                     ELSE cost 
                                 END as cost, 
                                 reverse_cost
                                 FROM graphs.edges
                                 WHERE geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326)',
                                $3::bigint[],
                                (SELECT minx FROM bbox_calc), (SELECT miny FROM bbox_calc),
                                (SELECT maxx FROM bbox_calc), (SELECT maxy FROM bbox_calc)
                            ),
                            $1::bigint, $2::bigint, directed := true
                        )
                    ),
                    ordered_path AS (
                        SELECT 
                            r1.seq, r1.node, r1.edge, r1.cost,
                            LEAD(r1.node) OVER (ORDER BY r1.seq) as next_node
                        FROM route r1
                        WHERE r1.edge > 0 OR r1.node = $2::bigint
                    )
                    SELECT 
                        op.seq,
                        op.node as from_node,
                        op.next_node as to_node,
                        op.edge,
                        op.cost,
                        e.length_m,
                        e.speed_limit_kmh as max_speed, 
                        ST_AsBinary(
                            CASE 
                                WHEN op.node = e.source_id THEN e.geometry
                                ELSE ST_Reverse(e.geometry)
                            END
                        ) as geom_wkb
                    FROM ordered_path op
                    LEFT JOIN graphs.edges e ON op.edge = e.id
                    WHERE op.edge != -1
                    ORDER BY op.seq
                """
                
                # Careful with $3 array injection.
                # format() in PG handles %L for literals.
                # But we are using asyncpg parameters.
                # Asyncpg $3 is a parameter.
                # pgr_dijkstra argument 1 is a TEXT query.
                # We can't bind asyncpg params INSIDE the string passed to pgr_dijkstra via asyncpg.
                # We must interpolate the array into the string.
                # Or use `format` with specific values.
                
                # Simplified approach: Construct the SQL in Python to avoid nesting hell.
                # But we want to use DB-side BBOX.
                
                # Let's use the provided snippet logic but fix parameter passing.
                # We can pass the penalized array as a parameter to the outer query, 
                # and use `format` to inject it into the inner query string?
                # No, standard trick:
                # pgr_dijkstra('... id = ANY($1) ...', ..., inputs) isn't standard pgr.
                
                # Strategy: Python f-string or manual array formatting.
                # penalized_edges is List[int].
                
                pen_str = "{" + ",".join(map(str, penalized_edges)) + "}"
                
                # Correct Query using Python formatting for the inner SQL part related to array
                # We use asyncpg for start/end nodes to be safe.
                # BBOX is calculated in CTE, so we need to fetch it or subquery it?
                # Actually, implementing BBOX logic inside python is faster for params?
                
                # User Requirement: "USE SAME optimized query structure ... Dynamic BBOX"
                # The user reference had SQL doing BBOX.
                
                # Let's try passing the array string and formatting it in PG.
                rows = await conn.fetch(query, start_node, end_node, penalized_edges)
                
                if not rows: break # No route found
                
                route = self._rows_to_route(rows)
                
                # Check uniqueness via Edge IDs
                is_unique = True
                current_set = set(route.edge_ids)
                for existing in routes:
                     if set(existing.edge_ids) == current_set:
                         is_unique = False
                         break
                
                if is_unique:
                    routes.append(route)
                    # Add edges to penalty
                    # Penalize ALL edges in the route
                    penalized_edges.extend(route.edge_ids)
                    # Deduplicate penalty list?
                    penalized_edges = list(set(penalized_edges))

            return routes

    async def snap_to_road(self, lat: float, lon: float, snap_radius_m: float = 100.0) -> Optional[Tuple[int, float]]:
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
            
        async with self.db_pool.acquire() as conn:
            # Direct KNN on Nodes (O(log N))
            # Finds minimal latency start node without expensive edge snapping
            query = """
                SELECT id, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography) as dist
                FROM graphs.nodes
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint($2, $1), 4326)
                LIMIT 1
            """
            row = await conn.fetchrow(query, lat, lon)
            
            if row and row['dist'] <= snap_radius_m:
                 # Return Node ID and fraction 0.0 (since we snap to node directly)
                 return (row['id'], 0.0)
            
            return None




    async def close(self) -> None:
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
