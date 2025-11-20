"""
Database connection pool manager.
Centralizes asyncpg pool with proper configuration.
"""

import asyncpg
from loguru import logger
from typing import Optional


class DatabasePool:
    """Manages PostgreSQL connection pool."""
    
    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        min_size: int = 5,
        max_size: int = 20,
        timeout: int = 10
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self, max_retries: int = 5) -> None:
        """
        Initialize connection pool with retries.
        
        Args:
            max_retries: Maximum connection attempts
        """
        import asyncio
        
        for attempt in range(1, max_retries + 1):
            try:
                self.pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    timeout=self.timeout
                )
                
                # Test connection
                async with self.pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                
                logger.success(
                    f"Connected to PostgreSQL: "
                    f"{self.host}:{self.port}/{self.database} "
                    f"(pool: {self.min_size}-{self.max_size})"
                )
                return
                
            except Exception as e:
                logger.warning(
                    f"DB connection attempt {attempt}/{max_retries} failed: "
                    f"{e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(2)
                else:
                    raise RuntimeError(
                        f"Failed to connect to DB after {max_retries} attempts"
                    )
    
    async def close(self) -> None:
        """Close connection pool gracefully."""
        if self.pool:
            await self.pool.close()
            logger.info("DB connection pool closed")
    
    def acquire(self):
        """
        Acquire connection from pool.
        
        Usage:
            async with db.acquire() as conn:
                result = await conn.fetchval("SELECT ...")
        """
        if not self.pool:
            raise RuntimeError("DB pool not initialized. Call connect() first")
        return self.pool.acquire()
