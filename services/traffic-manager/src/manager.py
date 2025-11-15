"""
Traffic Manager - real-time traffic state.

Manages:
- Edge loads (from Simulation Service sync)
- Congestion calculation (load / capacity)
- Redis cache for fast access
- Hotspot detection
"""

import asyncpg
import redis.asyncio as aioredis
from loguru import logger
from typing import List, Dict, Tuple


class TrafficManager:
    """
    Manage real-time traffic state.
    
    Design:
    - Receives edge loads from Simulation Service (every 1 sec)
    - Calculates congestion = current_load / capacity
    - Caches in Redis (TTL 5 sec)
    - Provides fast lookups for routing
    """
    
    def __init__(self):
        # Database connection
        self.db_pool: asyncpg.Pool = None
        
        # Redis cache
        self.redis_client: aioredis.Redis = None
        
        # Config (TODO: load from YAML)
        self.db_host = "localhost"
        self.db_port = 5432
        self.db_name = "osm"
        self.db_user = "postgres"
        self.db_password = "postgres"
        
        self.redis_host = "localhost"
        self.redis_port = 6379
        self.redis_ttl_sec = 5
        
        self.congestion_threshold = 0.8
        
        logger.info("TrafficManager initialized")
    
    async def initialize(self):
        """Initialize manager (setup DB pool, Redis)."""
        # PostgreSQL pool
        self.db_pool = await asyncpg.create_pool(
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            user=self.db_user,
            password=self.db_password,
            min_size=2,
            max_size=10
        )
        
        # Redis client
        self.redis_client = await aioredis.from_url(
            f"redis://{self.redis_host}:{self.redis_port}",
            decode_responses=False
        )
        
        logger.info("Traffic Manager initialized (DB + Redis ready)")
    
    async def shutdown(self):
        """Shutdown manager."""
        if self.db_pool:
            await self.db_pool.close()
        
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Traffic Manager shutdown complete")
    
    async def get_congestion_stats(self) -> Dict:
        """
        Get global congestion statistics.
        
        Calls graphs.get_congestion_stats() SQL function.
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM graphs.get_congestion_stats()"
            )
            
            return {
                "total_edges": row["total_edges"],
                "congested_edges": row["congested_edges"],
                "avg_congestion": row["avg_congestion"],
                "max_congestion": row["max_congestion"]
            }
    
    async def get_edge_congestion(
        self,
        edge_ids: List[int]
    ) -> Dict[int, float]:
        """
        Get congestion levels for specific edges.
        
        Strategy:
        1. Check Redis cache first
        2. If miss, query database
        3. Cache result
        """
        result = {}
        missing_ids = []
        
        # Check Redis cache
        for edge_id in edge_ids:
            key = f"congestion:{edge_id}"
            cached = await self.redis_client.get(key)
            
            if cached:
                result[edge_id] = float(cached)
            else:
                missing_ids.append(edge_id)
        
        # Query database for missing
        if missing_ids:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT 
                        edge_id,
                        CASE 
                            WHEN capacity > 0 THEN current_load / capacity
                            ELSE 0.0
                        END AS congestion
                    FROM graphs.edges
                    WHERE edge_id = ANY($1)
                    """,
                    missing_ids
                )
                
                for row in rows:
                    edge_id = row["edge_id"]
                    congestion = row["congestion"]
                    
                    result[edge_id] = congestion
                    
                    # Cache in Redis
                    key = f"congestion:{edge_id}"
                    await self.redis_client.setex(
                        key,
                        self.redis_ttl_sec,
                        str(congestion)
                    )
        
        return result
    
    async def get_hotspots(self, limit: int = 10) -> List[Tuple[int, float]]:
        """
        Get top N most congested edges.
        
        Returns: [(edge_id, congestion_level), ...]
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    edge_id,
                    CASE 
                        WHEN capacity > 0 THEN current_load / capacity
                        ELSE 0.0
                    END AS congestion
                FROM graphs.edges
                WHERE enabled = true
                  AND capacity > 0
                ORDER BY congestion DESC
                LIMIT $1
                """,
                limit
            )
            
            return [
                (row["edge_id"], row["congestion"])
                for row in rows
            ]
