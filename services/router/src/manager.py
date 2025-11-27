"""
Router Manager - K-shortest paths calculation with pluggable algorithms.

Supports:
- A* + Yen (custom Python, src/routing/)
- pgRouting (SQL-based, future)
"""

import yaml
from pathlib import Path
from loguru import logger
from typing import List

from .engine import RouteEngine, Route
from .astar_engine import AStarEngine


class RouterManager:
    """
    Calculate K alternative routes using pluggable engines.
    
    Design:
    - Loads config from configs/router.yaml
    - Selects engine: AStarEngine or PgRoutingEngine (future)
    - Two-level turn penalties (routing cost + agent physics)
    - Priority handling (emergency ignores congestion)
    - Agent modes (normal, hurry, cautious, emergency)
    """
    
    def __init__(self, config_path: str = "configs/router.yaml"):
        """
        Initialize router with config.
        
        Args:
            config_path: Path to router.yaml config
        """
        # Load config
        self.config = self._load_config(config_path)
        
        # Select engine based on config
        algorithm = self.config.get("algorithm", "astar")
        
        if algorithm == "astar":
            self.engine: RouteEngine = AStarEngine(self.config)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
        
        logger.info(
            "RouterManager initialized",
            algorithm=algorithm
        )
    
    def _load_config(self, config_path: str) -> dict:
        """Load YAML config."""
        import yaml
        
        full_path = Path(config_path)
        if not full_path.is_absolute():
            # Relative to project root
            project_root = Path(__file__).parent.parent.parent.parent
            full_path = project_root / config_path
        
        with open(full_path) as f:
            return yaml.safe_load(f)
        
        logger.success(f"Config loaded: {config_path}")
    
    async def initialize(self):
        """Initialize router engine."""
        await self.engine.initialize()
        logger.success("Router initialized")
    
    async def shutdown(self):
        """Shutdown router engine."""
        await self.engine.shutdown()
        logger.info("Router shutdown complete")
    
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
        Calculate K alternative routes using selected engine.
        
        Args:
            start_lat, start_lon: Start coordinates
            end_lat, end_lon: End coordinates
            k: Number of routes
            agent_mode: Agent behavior mode (normal, hurry, etc)
            priority: Agent priority (0-100, >=20 emergency)
        
        Returns:
            List of Route objects
        """
        # Use engine to calculate routes
        routes = await self.engine.calculate_routes(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            k=k,
            agent_mode=agent_mode,
            priority=priority
        )
        
        return routes
