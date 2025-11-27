"""Database connection pool"""

import asyncpg
from loguru import logger


class DatabasePool:
    """Async database connection pool"""
    
    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        min_size: int = 2,
        max_size: int = 10
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.min_size = min_size
        self.max_size = max_size
        self.pool: asyncpg.Pool = None
    
    async def connect(self):
        """Create connection pool"""
        self.pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
            min_size=self.min_size,
            max_size=self.max_size
        )
        logger.info(
            f"Connected to PostgreSQL: {self.host}:{self.port}/{self.database} "
            f"(pool: {self.min_size}-{self.max_size})"
        )
    
    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("DB connection pool closed")
    
    def acquire(self):
        """Acquire connection from pool"""
        return self.pool.acquire()
