"""
Coordinator Manager - orchestration logic.

Manages:
- Route calculation (K-shortest paths with diversity)
- Agent lifecycle (create/remove)
- Rerouting (congestion-based)
- Integration with Simulation Service
"""

import asyncio
import time
from typing import List, Dict, Optional, Callable

import httpx
from loguru import logger


class CoordinatorManager:
    """
    Coordinate multi-agent navigation.
    
    Design:
    - Stateless (agents managed by Simulation Service)
    - Orchestrates: Router + Simulation + Traffic Manager
    - Broadcasts positions via WebSocket callback
    """
    
    def __init__(self):
        # Service URLs (from config or env)
        self.simulation_url = "http://localhost:8001"
        self.router_url = "http://localhost:8003"  # Phase 4
        self.traffic_url = "http://localhost:8004"  # Phase 5
        
        # HTTP client (persistent connection pool)
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Rerouting state
        self.rerouting_enabled = True
        self.rerouting_strategy = "hybrid"  # From config
        self.check_interval_sec = 5
        self.congestion_threshold = 0.8
        self.last_rerouting_time = 0.0
        self.agents_rerouted = 0
        
        # WebSocket broadcast callback (set by main.py)
        self.broadcast_callback: Optional[Callable] = None
        
        # Agent registry (agent_id -> metadata)
        self.agents: Dict[str, Dict] = {}
        
        logger.info("CoordinatorManager initialized")
    
    async def initialize(self):
        """Initialize coordinator (setup HTTP client, etc)."""
        self.http_client = httpx.AsyncClient(timeout=30.0)
        
        # Start position polling loop
        asyncio.create_task(self._position_poll_loop())
        
        # TODO: Start rerouting loop
        # asyncio.create_task(self._rerouting_loop())
        
        logger.info("Coordinator initialized")
    
    async def shutdown(self):
        """Shutdown coordinator."""
        if self.http_client:
            await self.http_client.aclose()
        
        logger.info("Coordinator shutdown complete")
    
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
        
        Uses pgRouting with diversity penalties.
        Priority >= 20: ignores congestion.
        """
        # TODO: Call Router Service
        # For now, placeholder
        logger.info(
            f"Calculating {k} routes: "
            f"({start_lat},{start_lon}) → ({end_lat},{end_lon}), "
            f"priority={priority}"
        )
        
        # Mock response (will implement in Phase 4)
        return [
            {
                "route_id": 1,
                "segments": [],
                "total_distance_m": 5000.0,
                "estimated_time_sec": 300.0,
                "diversity_score": 1.0
            }
        ]
    
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
        Create agent and register with Simulation Service.
        
        Flow:
        1. Calculate route (if not provided)
        2. Call Simulation Service POST /simulation/agents
        3. Register in agents dict
        4. Return agent_id
        """
        # Calculate route if needed
        if route_edge_ids is None:
            routes = await self.calculate_routes(
                start_lat, start_lon,
                end_lat, end_lon,
                k=3, priority=priority,
                agent_type=agent_type
            )
            
            # Select best route (first for now)
            # TODO: Implement route selection logic
            route_edge_ids = routes[0].get("edge_ids", [1, 2, 3])
        
        # Register with Simulation Service
        response = await self.http_client.post(
            f"{self.simulation_url}/simulation/agents",
            json={
                "route_edge_ids": route_edge_ids,
                "start_lat": start_lat,
                "start_lon": start_lon,
                "agent_type": agent_type,
                "config_overrides": None
            }
        )
        
        if response.status_code != 200:
            raise RuntimeError(
                f"Simulation Service failed: {response.text}"
            )
        
        data = response.json()
        agent_id = data["agent_id"]
        
        # Register in coordinator
        self.agents[agent_id] = {
            "priority": priority,
            "agent_type": agent_type,
            "route_edge_ids": route_edge_ids,
            "created_at": time.time()
        }
        
        logger.info(f"Agent created: {agent_id} (priority={priority})")
        
        return agent_id
    
    async def remove_agent(self, agent_id: str):
        """Remove agent from system."""
        if agent_id not in self.agents:
            raise KeyError(f"Agent {agent_id} not found")
        
        # Remove from Simulation Service
        response = await self.http_client.delete(
            f"{self.simulation_url}/simulation/agents/{agent_id}"
        )
        
        if response.status_code != 200:
            logger.warning(
                f"Simulation Service removal failed: {response.text}"
            )
        
        # Remove from coordinator
        del self.agents[agent_id]
        
        logger.info(f"Agent removed: {agent_id}")
    
    def get_agent_count(self) -> int:
        """Get number of managed agents."""
        return len(self.agents)
    
    async def get_rerouting_status(self) -> Dict:
        """Get rerouting service status."""
        return {
            "enabled": self.rerouting_enabled,
            "strategy": self.rerouting_strategy,
            "check_interval_sec": self.check_interval_sec,
            "last_rerouting_time": self.last_rerouting_time,
            "agents_rerouted": self.agents_rerouted,
            "congestion_threshold": self.congestion_threshold
        }
    
    async def _rerouting_loop(self):
        """
        Periodic rerouting check.
        
        Strategy (hybrid):
        1. Check every 5 seconds
        2. Identify agents on congested edges (> 80% capacity)
        3. Recalculate routes for those agents
        4. Update via Simulation Service
        """
        logger.info("Rerouting loop started")
        
        while self.rerouting_enabled:
            try:
                await asyncio.sleep(self.check_interval_sec)
                
                # TODO: Implement rerouting logic
                # 1. Get congestion data from Traffic Manager
                # 2. Identify agents to reroute
                # 3. Calculate new routes
                # 4. Update Simulation Service
                
            except Exception as e:
                logger.error(f"Rerouting error: {e}", exc_info=e)
    
    async def _position_poll_loop(self):
        """
        Poll Simulation Service for agent positions.
        
        Polls every 0.5 sec (2 FPS for GUI).
        Broadcasts to WebSocket clients via callback.
        """
        logger.info("Position polling loop started")
        
        while True:
            try:
                await asyncio.sleep(0.5)  # 2 Hz polling
                
                if len(self.agents) == 0:
                    continue
                
                # Get all agent positions from Simulation
                positions = []
                
                for agent_id in self.agents.keys():
                    try:
                        response = await self.http_client.get(
                            f"{self.simulation_url}/simulation/agents/"
                            f"{agent_id}/position"
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            positions.append({
                                "agent_id": agent_id,
                                "lat": data["lat"],
                                "lon": data["lon"],
                                "edge_id": data.get("edge_id"),
                                "speed_mps": data.get("current_speed_mps")
                            })
                    except Exception as e:
                        logger.debug(
                            f"Failed to get position for {agent_id}: {e}"
                        )
                
                # Broadcast to GUI clients
                if positions and self.broadcast_callback:
                    await self.broadcast_callback(positions)
                
            except Exception as e:
                logger.error(f"Position polling error: {e}", exc_info=e)
                await asyncio.sleep(1.0)  # Backoff on error
