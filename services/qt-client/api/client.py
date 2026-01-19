"""Unified API Client for Gateway Interaction"""
import httpx
from loguru import logger
from typing import List, Dict, Optional, Any
from services.common.config import config_loader

class ApiClient:
    """
    Unified client for communicating with the Gateway service.
    
    Handles:
    - Routing requests (/routing/find)
    - Graph data (/osm/fetch_road_graph) (Via worker usually, but exposed here too)
    - Tile requests (generic helper)
    """
    
    def __init__(self, gateway_url: str):
        self.base_url = gateway_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"ApiClient initialized with gateway: {self.base_url}")
        
    async def close(self):
        await self.client.aclose()
        
    def _url(self, path: str) -> str:
        """Construct full URL."""
        return f"{self.base_url}{path}"

    async def find_routes(
        self, 
        points: List[Dict[str, float]], 
        k: int = 3,
        agent_type: str = "car_normal"
    ) -> Dict[str, Any]:
        """
        Request route calculation between points.
        
        Args:
            points: List of dicts, e.g. [{"lat": 55.7, "lon": 37.6}, ...]
            k: Number of routes (ignored by current server implementation)
            agent_type: Profile name
            
        Returns:
            JSON response dictionary containing routes
        """
        url = self._url("/routing/calculate")
        payload = {
            "waypoints": points,
            "priority": 0,
            # "agent_type": agent_type # Not yet supported by server model
        }
        
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Routing request failed: {e}")
            raise

    # Note: Fetching graph/tiles is often done via standard synchronous requests (requests lib)
    # inside QThreads (Qt Workers) separately to avoid async event loop conflicts with PyQt.
    # See api_workers.py for those implementations.
