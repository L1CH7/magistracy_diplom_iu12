"""
Router Manager - K-shortest paths calculation.

Uses pgRouting (Yen's algorithm) + diversity penalties.
"""

import asyncpg
from loguru import logger
from typing import List, Dict


class RouterManager:
    """
    Calculate K alternative routes with diversity.
    
    Design:
    - Uses pgRouting's pgr_ksp (Yen's algorithm)
    - Applies progressive penalties to shared edges
    - Two-level turn penalties (routing cost + agent physics)
    - Priority handling (emergency ignores congestion)
    """
    
    def __init__(self):
        # Database connection
        self.db_pool: asyncpg.Pool = None
        
        # Config (TODO: load from YAML)
        self.db_host = "localhost"
        self.db_port = 5432
        self.db_name = "osm"
        self.db_user = "postgres"
        self.db_password = "postgres"
        
        logger.info("RouterManager initialized")
    
    async def initialize(self):
        """Initialize router (setup DB pool)."""
        self.db_pool = await asyncpg.create_pool(
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
            min_size=2,
            max_size=10
        )
        
        logger.info("Router initialized (DB pool ready)")
    
    async def shutdown(self):
        """Shutdown router."""
        if self.db_pool:
            await self.db_pool.close()
        
        logger.info("Router shutdown complete")
    
    async def calculate_routes(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        k: int = 3,
        penalty_factor: float = 1.5,
        diversity_threshold: float = 0.3,
        priority: int = 0,
        agent_type: str = "car_normal"
    ) -> List[Dict]:
        """
        Calculate K alternative routes.
        
        Algorithm:
        1. Find nearest nodes (start/end)
        2. Call pgRouting k-shortest paths
        3. Apply diversity penalties (progressive)
        4. Filter by diversity_threshold
        5. Return routes with metadata
        """
        async with self.db_pool.acquire() as conn:
            # Step 1: Find nearest nodes
            start_node = await self._find_nearest_node(
                conn, start_lat, start_lon
            )
            end_node = await self._find_nearest_node(
                conn, end_lat, end_lon
            )
            
            logger.info(
                f"Routing: node {start_node} → {end_node}, k={k}"
            )
            
            # Step 2: Call pgRouting with diversity
            routes = await self._calculate_k_routes_with_diversity(
                conn,
                start_node,
                end_node,
                k,
                penalty_factor,
                diversity_threshold,
                priority
            )
            
            return routes
    
    async def _find_nearest_node(
        self,
        conn: asyncpg.Connection,
        lat: float,
        lon: float
    ) -> int:
        """Find nearest graph node to coordinates."""
        query = """
        SELECT node_id
        FROM graphs.nodes
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
        LIMIT 1
        """
        
        row = await conn.fetchrow(query, lon, lat)
        
        if not row:
            raise ValueError(f"No nodes found near ({lat}, {lon})")
        
        return row["node_id"]
    
    async def _calculate_k_routes_with_diversity(
        self,
        conn: asyncpg.Connection,
        start_node: int,
        end_node: int,
        k: int,
        penalty_factor: float,
        diversity_threshold: float,
        priority: int
    ) -> List[Dict]:
        """
        Calculate K routes with diversity penalties.
        
        Uses graphs.get_k_routes_with_diversity() SQL function.
        (Will create in Phase 4 migration)
        """
        query = """
        SELECT *
        FROM graphs.get_k_routes_with_diversity(
            $1, $2, $3, $4, $5, $6
        )
        """
        
        rows = await conn.fetch(
            query,
            start_node,
            end_node,
            k,
            penalty_factor,
            diversity_threshold,
            priority
        )
        
        # Parse routes
        routes = []
        for row in rows:
            routes.append({
                "route_id": row["route_id"],
                "segments": row["segments"],  # JSONB array
                "total_distance_m": row["total_distance_m"],
                "estimated_time_sec": row["estimated_time_sec"],
                "diversity_score": row["diversity_score"],
                "edge_ids": row["edge_ids"]
            })
        
        logger.info(f"Found {len(routes)} routes")
        
        return routes
