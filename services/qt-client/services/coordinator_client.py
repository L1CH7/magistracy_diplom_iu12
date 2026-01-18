"""
HTTP client for Coordinator Service API.

Handles:
- Route calculation
- Agent creation
- Agent removal
"""

import httpx
from loguru import logger
from typing import List, Dict, Optional


class CoordinatorAPIClient:
    """
    HTTP client for Coordinator Service.
    
    Usage:
        client = CoordinatorAPIClient("http://localhost:8002")
        routes = await client.calculate_routes(55.7558, 37.6173, ...)
    """
    
    def __init__(self, gateway_url: str = "http://localhost:8000"):
        self.base_url = gateway_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
        logger.info(f"CoordinatorAPIClient created: {gateway_url}")
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def calculate_routes(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        k: int = 3,
        priority: int = 0,
        agent_type: str = "car_normal"
    ) -> List[Dict]:
        """
        Calculate K alternative routes.

        Returns: List of routes with segments, distance, time.
        """
        # Gateway path
        url = f"{self.base_url}/routing/find"

        payload = {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
            "k": k,
            "priority": priority,
            "agent_type": agent_type
        }

        response = await self.client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        return data["routes"]
    
    async def create_agent(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        route_edge_ids: Optional[List[int]] = None,
        priority: int = 0,
        agent_type: str = "car_normal"
    ) -> str:
        """
        Create agent with route.
        
        Returns: agent_id
        """
        url = f"{self.base_url}/api/v1/agents"
        
        payload = {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
            "route_edge_ids": route_edge_ids,
            "priority": priority,
            "agent_type": agent_type
        }
        
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        return data["agent_id"]
    
    async def remove_agent(self, agent_id: str):
        """Remove agent."""
        url = f"{self.base_url}/api/v1/agents/{agent_id}"
        
        response = await self.client.delete(url)
        response.raise_for_status()
    
    async def get_rerouting_status(self) -> Dict:
        """Get rerouting service status."""
        url = f"{self.base_url}/api/v1/rerouting/status"
        
        response = await self.client.get(url)
        response.raise_for_status()
        
        return response.json()
