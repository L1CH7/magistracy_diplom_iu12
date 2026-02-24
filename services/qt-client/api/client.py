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
        k: int = 1,
        priority: int = 0
    ) -> Dict[str, Any]:
        """
        Request route calculation between points.
        
        Args:
            points: List of dicts, e.g. [{"lat": 55.7, "lon": 37.6}, ...]
            k: Number of routes/alternatives
            priority: Routing priority factor (0-100)
            
        Returns:
            JSON response dictionary containing routes
        """
        url = self._url("/routing/calculate")
        payload = {
            "waypoints": points,
            "priority": priority,
            "k": k
        }
        
        try:
            response = await self.client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Routing request failed: {e}")
            raise

    def find_routes_sync(
        self, 
        points: List[Dict[str, float]], 
        k: int = 1,
        priority: int = 0
    ) -> Dict[str, Any]:
        """
        Synchronous version of find_routes for use in QThreads/blocking contexts.
        Uses 'requests' library.
        """
        import requests
        import json
        url = self._url("/routing/calculate")
        payload = {
            "waypoints": points,
            "priority": priority,
            "k": k
        }
        
        # TRACE: Log request
        logger.trace(f"POST {url}")
        logger.trace(f"Request payload: {json.dumps(payload, indent=2)}")
        
        try:
            response = requests.post(url, json=payload, timeout=60.0)
            
            # TRACE: Log response
            logger.trace(f"Response status: {response.status_code}")
            try:
                resp_json = response.json()
                # Truncate geometry for readability
                routes_count = len(resp_json.get("routes", []))
                logger.trace(f"Response: {routes_count} routes returned")
                logger.trace(f"Response body: {json.dumps(resp_json, indent=2)[:2000]}...")
            except Exception:
                logger.trace(f"Response body (raw): {response.text[:500]}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Routing request failed: {e}")
            raise
