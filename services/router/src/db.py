"""
Database connection pool wrapper.
"""
import asyncpg
from loguru import logger

class DatabasePool:
    def __init__(self, host, port, database, user, password):
        self.dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        self.pool = None

    async def connect(self):
        """Create connection pool."""
        logger.info(f"Connecting to DB at {self.dsn.split('@')[-1]}...")
        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=2,
            max_size=10
        )
        logger.info("Database pool connected")

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Database pool closed")

    def acquire(self):
        """Acquire connection from pool."""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        return self.pool.acquire()
