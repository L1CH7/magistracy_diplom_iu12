"""
pgRouting-based implementation of RoutingEngine.
"""

from typing import List, Optional, Tuple, Dict, Any
import asyncpg
from loguru import logger
import json

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
            # Optimized Dijkstra query with BBOX pre-filtering
            # We must pass the BBOX as parameters to the inner SQL string because it runs in a separate context
            query = """
                WITH 
                start_n AS (SELECT geom FROM graphs.nodes WHERE id = $1),
                end_n AS (SELECT geom FROM graphs.nodes WHERE id = $2),
                -- Calculate BBOX bounds (minx, miny, maxx, maxy) + padding
                bbox_coords AS (
                    SELECT 
                        ST_XMin(box) as minx,
                        ST_YMin(box) as miny,
                        ST_XMax(box) as maxx,
                        ST_YMax(box) as maxy
                    FROM (
                        SELECT ST_Expand(ST_Envelope(ST_MakeLine(start_n.geom, end_n.geom)), 0.02) as box 
                        FROM start_n, end_n
                    ) sub
                ),
                route AS (
                    SELECT * FROM pgr_dijkstra(
                        format(
                            'SELECT 
                                id, 
                                source_id as source, 
                                target_id as target, 
                                base_travel_time_sec as cost, 
                                CASE 
                                    WHEN oneway THEN -1.0 
                                    ELSE base_travel_time_sec 
                                END as reverse_cost 
                            FROM graphs.edges 
                            WHERE geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326)',
                            (SELECT minx FROM bbox_coords),
                            (SELECT miny FROM bbox_coords),
                            (SELECT maxx FROM bbox_coords),
                            (SELECT maxy FROM bbox_coords)
                        ),
                        $1, $2, directed := true
                    )
                ),
                ordered_path AS (
                    SELECT 
                        r1.seq,
                        r1.node AS from_node,
                        r2.node AS to_node,
                        r1.edge
                    FROM route r1
                    JOIN route r2 ON r1.seq + 1 = r2.seq
                    WHERE r1.edge > 0
                )
                SELECT 
                    op.seq,
                    op.from_node,
                    op.to_node,
                    op.edge,
                    e.length_m,
                    e.max_speed,
                    (CASE 
                        WHEN op.from_node = e.target_id THEN ST_AsGeoJSON(ST_Reverse(e.geometry))
                        ELSE ST_AsGeoJSON(e.geometry)
                    END)::jsonb as geometry_json
                FROM ordered_path op
                LEFT JOIN graphs.edges e ON op.edge = e.id
                ORDER BY op.seq
            """
            rows = await conn.fetch(query, start_node, end_node)
            if not rows:
                raise RouteNotFoundError(f"No route from {start_node} to {end_node}")
            
            return self._rows_to_route(rows)

    async def find_k_routes(self, start_node: int, end_node: int, k: int = 3, priority: int = 0, use_diversity: bool = False) -> List[Route]:
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
            
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT 
                    route_id,
                    segments,
                    total_distance_m,
                    estimated_time_sec,
                    diversity_score,
                    edge_ids
                FROM graphs.get_k_routes_with_diversity($1, $2, $3, 1.5, 0.3, $4)
            """
            rows = await conn.fetch(query, start_node, end_node, k, priority)
            
            if not rows:
                return []
                
            routes = []
            for row in rows:
                raw_seg = row['segments']
                if isinstance(raw_seg, str):
                    seg_list = json.loads(raw_seg)
                else:
                    seg_list = raw_seg
                
                final_segments = []
                node_sequence = []
                if seg_list:
                    node_sequence.append(seg_list[0]['from_node'])
                    for s in seg_list:
                        # Extract geometry
                        geom = s.get('geometry')
                        if isinstance(geom, str):
                            geom = json.loads(geom)
                            
                        final_segments.append({
                            **s,
                            "geometry_json": geom
                        })
                        node_sequence.append(s['to_node'])

                routes.append(Route(
                    edge_ids=row['edge_ids'],
                    total_cost=float(row['estimated_time_sec'] or 0.0),
                    total_distance_m=float(row['total_distance_m']),
                    algorithm=RoutingAlgorithm.PGROUTING.value,
                    node_sequence=node_sequence,
                    segments=final_segments
                ))
            
            return routes

    def _rows_to_route(self, rows: List[Any]) -> Route:
        """Helper to convert DB result rows to Route object."""
        segments = []
        total_distance = 0.0
        total_cost = 0.0
        node_sequence = []
        
        for row in rows:
            # Check edge validity (pgRouting often returns -1 for last node)
            if row.get('edge') == -1 or row['edge'] is None:
                if 'node' in row:
                     node_sequence.append(row['node'])
                elif 'from_node' in row:
                     node_sequence.append(row['from_node'])
                continue
                
            dist = float(row['length_m'] or 0)
            cost = float(row.get('cost', dist/60.0)) # Fallback if cost not in rows
            
            # Extract geometry
            geom = row.get('geometry_json')
            if isinstance(geom, str):
                geom = json.loads(geom)

            segment = {
                "edge_id": row['edge'],
                "from_node": row.get('from_node') or row.get('source'),
                "to_node": row.get('to_node') or row.get('target'),
                "distance_m": dist,
                "speed_limit": float(row.get('max_speed') or 60.0),
                "geometry_json": geom
            }
            segments.append(segment)
            total_distance += dist
            total_cost += cost
            if 'from_node' in row:
                node_sequence.append(row['from_node'])
            elif 'node' in row:
                node_sequence.append(row['node'])
        
        # Add the final node
        if rows and 'to_node' in rows[-1]:
            node_sequence.append(rows[-1]['to_node'])

        return Route(
            edge_ids=[s['edge_id'] for s in segments],
            total_cost=total_cost,
            total_distance_m=total_distance,
            algorithm=RoutingAlgorithm.PGROUTING.value,
            node_sequence=node_sequence,
            segments=segments
        )


    async def snap_to_road(self, lat: float, lon: float, snap_radius_m: float = 100.0) -> Optional[Tuple[int, float]]:
        if not self.db_pool:
            raise RuntimeError("PgRoutingEngine not initialized")
            
        async with self.db_pool.acquire() as conn:
            # Fetch closest edges with their source/target IDs and nodes
            query = """
                SELECT 
                    e.id, 
                    e.source_id,
                    e.target_id,
                    e.highway_type,
                    ST_Distance(
                        e.geometry::geography, 
                        ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography
                    ) as dist,
                    ST_LineLocatePoint(e.geometry, ST_SetSRID(ST_MakePoint($2, $1), 4326)) as fraction
                FROM graphs.edges e
                ORDER BY 
                    e.geometry <-> ST_SetSRID(ST_MakePoint($2, $1), 4326) ASC
                LIMIT 5
            """
            rows = await conn.fetch(query, lat, lon)
            
            candidates = [r for r in rows if r['dist'] <= snap_radius_m]
            if not candidates:
                return None
            
            def is_main_road(htype):
                return htype not in ('service', 'track', 'footway', 'path', 'cycleway', 'steps', 'pedestrian')

            best_edge = candidates[0]
            if not is_main_road(best_edge['highway_type']):
                # Heuristic: If closest is service/track, look for a main road nearby.
                # Use a generous threshold to escape parking lots/service roads.
                # Allow up to 100m or 5x the distance to the service road, whichever is larger,
                # but capped by the hard snap_radius_m.
                limit_dist = max(best_edge['dist'] * 5.0, 100.0)
                
                for c in candidates[1:]:
                    if c['dist'] > limit_dist:
                        break
                    if is_main_road(c['highway_type']):
                        best_edge = c
                        break
            
            # Return closer node based on fraction
            # fraction 0.0 is start (source), 1.0 is end (target)
            node_id = best_edge['source_id'] if best_edge['fraction'] <= 0.5 else best_edge['target_id']
            return (node_id, 0.0)

    async def close(self) -> None:
        if self.db_pool:
            await self.db_pool.close()
            self.db_pool = None
