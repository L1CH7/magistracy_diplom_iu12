"""
Simulation Manager - core simulation logic.

Manages agent batch and simulation tick loop.
"""

import asyncio
import os
import time
from typing import Dict, List, Tuple, Optional

import numpy as np
from loguru import logger

from src.shared.agent import (
    AgentBatch,
    GraphCache,
    move_batch,
    get_agent_config_manager
)
from .models import (  # noqa: E402
    AgentPosition,
    AgentStateResponse,
    SimulationStatusResponse
)


class SimulationManager:
    """
    Manages simulation state and tick loop.
    
    Design:
    - Holds agent batch (numpy arrays)
    - Runs async tick loop (20 FPS)
    - Provides API for adding/removing/updating agents
    - Broadcasts positions to Coordinator
    """
    
    def __init__(self):
        self.batch: Optional[AgentBatch] = None
        self.graph_cache: Optional[GraphCache] = None
        self.config_manager = get_agent_config_manager()
        
        # Simulation state
        self.is_running = False
        self.fps = 20
        self.dt = 1.0 / self.fps
        self.start_time = 0.0
        self.tick_count = 0
        
        # Agent index mapping (agent_id -> batch_index)
        self.agent_indices: Dict[str, int] = {}
        self.next_agent_id = 1
        
        # Tick loop task
        self.tick_task: Optional[asyncio.Task] = None
        
        logger.info("SimulationManager initialized")
    
    async def initialize(self, load_graph: bool = True):
        """
        Initialize simulation (load graph cache, etc).
        
        Args:
            load_graph: Whether to load graph from database (default True)
        """
        # Create empty batch
        self.batch = self._create_empty_batch()
        
        # Load graph cache from database
        if load_graph:
            await self._load_graph_cache()
        
        logger.info("Simulation initialized")
    
    async def shutdown(self):
        """Shutdown simulation."""
        if self.is_running:
            await self.stop()
        
        logger.info("Simulation shutdown complete")
    
    async def start(self):
        """Start simulation tick loop."""
        if self.is_running:
            raise RuntimeError("Simulation already running")
        
        self.is_running = True
        self.start_time = time.time()
        self.tick_count = 0
        
        # Start tick loop
        self.tick_task = asyncio.create_task(self._tick_loop())
        
        logger.info("Simulation started")
    
    async def stop(self):
        """Stop simulation tick loop."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Wait for tick loop to finish
        if self.tick_task:
            await self.tick_task
            self.tick_task = None
        
        logger.info("Simulation stopped")
    
    async def _tick_loop(self):
        """Main simulation loop (runs at fps)."""
        logger.info(f"Tick loop started @ {self.fps} FPS")
        
        try:
            while self.is_running:
                tick_start = time.perf_counter()
                
                # Update all agents
                await self._tick()
                
                tick_duration = time.perf_counter() - tick_start
                
                # Sleep for remaining time to maintain FPS
                sleep_time = self.dt - tick_duration
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    # Tick took longer than dt - log warning
                    tick_ms = tick_duration * 1000
                    target_ms = self.dt * 1000
                    logger.warning(
                        f"Tick {self.tick_count} took {tick_ms:.1f}ms "
                        f"(target: {target_ms:.1f}ms)"
                    )
                
                self.tick_count += 1
                
                # DB sync every 5 seconds (100 ticks @ 20 FPS)
                if self.tick_count % (self.fps * 5) == 0:
                    await self._sync_agents_to_db()
                
                # Log stats every second
                if self.tick_count % self.fps == 0:
                    self._log_stats()
                    
        except Exception as e:
            logger.error(f"Tick loop error: {e}", exc_info=e)
            self.is_running = False
    
    async def _tick(self):
        """Single simulation tick."""
        if self.batch is None or self.batch.size == 0:
            return
        
        # Update all agents at once (vectorized!)
        try:
            self.batch = move_batch(
                self.batch,
                self.dt,
                self.graph_cache,
                use_gpu=False  # GPU not available in Docker by default
            )
            
            # Teleport detection (if enabled)
            # TODO: implement teleport detection
            
            # Broadcast positions to Coordinator
            # TODO: implement WebSocket broadcast
            
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=e)
    
    def _log_stats(self):
        """Log simulation statistics."""
        if self.batch is None:
            return
        
        n_running = self.batch.is_running.sum()
        n_completed = self.batch.reached_destination.sum()
        elapsed = time.time() - self.start_time
        
        logger.info(
            f"Sim stats: {n_running} running, {n_completed} completed, "
            f"{elapsed:.1f}s elapsed, tick {self.tick_count}"
        )
    
    async def add_agent(
        self,
        route_edge_ids: List[int],
        start_lat: float,
        start_lon: float,
        agent_type: str = 'car_normal',
        config_overrides: Optional[Dict] = None
    ) -> str:
        """
        Add new agent to simulation.
        
        Returns:
            Agent ID
        """
        # Generate agent ID
        agent_id = f"agent_{self.next_agent_id}"
        self.next_agent_id += 1
        
        # Load agent config (stored in batch config_indices)
        # TODO: implement multiple config types support
        if config_overrides:
            # Custom config - store separately
            _ = self.config_manager.create_custom(
                base=agent_type,
                **config_overrides
            )
        
        # Get starting edge from route
        if not route_edge_ids:
            raise ValueError("Route cannot be empty")
        
        start_edge_id = route_edge_ids[0]
        
        # Add to batch (grow arrays)
        if self.batch is None or self.batch.size == 0:
            # Create first agent
            self.batch = AgentBatch(
                agent_ids=np.array([agent_id], dtype=object),
                lats=np.array([start_lat]),
                lons=np.array([start_lon]),
                edge_ids=np.array([start_edge_id], dtype=np.int64),
                edge_progress=np.array([0.0]),
                route_edge_ids=np.array([route_edge_ids], dtype=object),
                route_indices=np.array([0], dtype=np.int64),
                speeds_mps=np.array([0.0]),
                bearings_deg=np.array([0.0]),
                start_times=np.array([time.time()]),
                elapsed_times=np.array([0.0]),
                is_running=np.array([True]),
                reached_destination=np.array([False]),
                config_indices=np.array([0], dtype=np.int32),
                total_distances_m=np.array([0.0])
            )
            batch_index = 0
        else:
            # Append to existing batch
            batch_index = self.batch.size
            self.batch = AgentBatch(
                agent_ids=np.append(self.batch.agent_ids, agent_id),
                lats=np.append(self.batch.lats, start_lat),
                lons=np.append(self.batch.lons, start_lon),
                edge_ids=np.append(self.batch.edge_ids, start_edge_id),
                edge_progress=np.append(self.batch.edge_progress, 0.0),
                route_edge_ids=np.append(
                    self.batch.route_edge_ids, route_edge_ids
                ),
                route_indices=np.append(self.batch.route_indices, 0),
                speeds_mps=np.append(self.batch.speeds_mps, 0.0),
                bearings_deg=np.append(self.batch.bearings_deg, 0.0),
                start_times=np.append(self.batch.start_times, time.time()),
                elapsed_times=np.append(self.batch.elapsed_times, 0.0),
                is_running=np.append(self.batch.is_running, True),
                reached_destination=np.append(
                    self.batch.reached_destination, False
                ),
                config_indices=np.append(self.batch.config_indices, 0),
                total_distances_m=np.append(self.batch.total_distances_m, 0.0)
            )
        
        # Store mapping
        self.agent_indices[agent_id] = batch_index
        
        logger.info(f"Added agent {agent_id} (type={agent_type})")
        
        return agent_id
    
    async def remove_agent(self, agent_id: str):
        """Remove agent from simulation."""
        if agent_id not in self.agent_indices:
            raise KeyError(f"Agent {agent_id} not found")
        
        # Get index
        index = self.agent_indices[agent_id]
        
        # Remove from batch (create mask)
        mask = np.ones(self.batch.size, dtype=bool)
        mask[index] = False
        
        self.batch = AgentBatch(
            agent_ids=self.batch.agent_ids[mask],
            lats=self.batch.lats[mask],
            lons=self.batch.lons[mask],
            edge_ids=self.batch.edge_ids[mask],
            edge_progress=self.batch.edge_progress[mask],
            route_edge_ids=self.batch.route_edge_ids[mask],
            route_indices=self.batch.route_indices[mask],
            speeds_mps=self.batch.speeds_mps[mask],
            bearings_deg=self.batch.bearings_deg[mask],
            start_times=self.batch.start_times[mask],
            elapsed_times=self.batch.elapsed_times[mask],
            is_running=self.batch.is_running[mask],
            reached_destination=self.batch.reached_destination[mask],
            config_indices=self.batch.config_indices[mask],
            total_distances_m=self.batch.total_distances_m[mask]
        )
        
        # Update indices (all agents after removed one shift down)
        del self.agent_indices[agent_id]
        for aid, idx in list(self.agent_indices.items()):
            if idx > index:
                self.agent_indices[aid] = idx - 1
        
        logger.info(f"Removed agent {agent_id}")
    
    async def update_route(
        self,
        agent_id: str,
        new_route: List[int]
    ) -> Tuple[bool, Optional[int]]:
        """
        Update agent route (if can switch).
        
        Returns:
            (success, new_route_index)
        """
        if agent_id not in self.agent_indices:
            raise KeyError(f"Agent {agent_id} not found")
        
        # Get agent index
        index = self.agent_indices[agent_id]
        
        # Check if can switch (TODO: implement with graph_edges)
        # For now, always allow switch
        can_switch = True
        new_index = 0
        
        if can_switch:
            # Update route in batch
            self.batch.route_edge_ids[index] = new_route
            self.batch.route_indices[index] = new_index
            return True, new_index
        else:
            return False, None
    
    def get_agent_position(self, agent_id: str) -> AgentPosition:
        """Get current agent position."""
        if agent_id not in self.agent_indices:
            raise KeyError(f"Agent {agent_id} not found")
        
        index = self.agent_indices[agent_id]
        
        return AgentPosition(
            lat=float(self.batch.lats[index]),
            lon=float(self.batch.lons[index]),
            speed_mps=float(self.batch.speeds_mps[index]),
            bearing_degrees=float(self.batch.bearings_deg[index]),
            edge_id=int(self.batch.edge_ids[index]),
            edge_progress=float(self.batch.edge_progress[index])
        )
    
    def get_agent_state(self, agent_id: str) -> AgentStateResponse:
        """Get full agent state."""
        if agent_id not in self.agent_indices:
            raise KeyError(f"Agent {agent_id} not found")
        
        index = self.agent_indices[agent_id]
        
        return AgentStateResponse(
            agent_id=agent_id,
            position=self.get_agent_position(agent_id),
            is_running=bool(self.batch.is_running[index]),
            reached_destination=bool(self.batch.reached_destination[index]),
            total_distance_m=float(self.batch.total_distances_m[index]),
            elapsed_time=float(self.batch.elapsed_times[index])
        )
    
    def list_agents(self) -> List[str]:
        """List all agent IDs."""
        if self.batch is None:
            return []
        return list(self.batch.agent_ids)
    
    def get_agent_count(self) -> int:
        """Get total agent count."""
        if self.batch is None:
            return 0
        return self.batch.size
    
    def get_status(self) -> SimulationStatusResponse:
        """Get simulation status."""
        if self.batch is None or self.batch.size == 0:
            return SimulationStatusResponse(
                is_running=self.is_running,
                fps=self.fps,
                agent_count=0,
                running_agents=0,
                completed_agents=0,
                elapsed_time=0.0,
                total_distance_m=0.0
            )
        
        n_running = int(self.batch.is_running.sum())
        n_completed = int(self.batch.reached_destination.sum())
        total_dist = float(self.batch.total_distances_m.sum())
        
        elapsed = time.time() - self.start_time if self.is_running else 0.0
        
        return SimulationStatusResponse(
            is_running=self.is_running,
            fps=self.fps,
            agent_count=self.batch.size,
            running_agents=n_running,
            completed_agents=n_completed,
            elapsed_time=elapsed,
            total_distance_m=total_dist
        )
    
    def _create_empty_batch(self) -> AgentBatch:
        """Create empty batch."""
        return AgentBatch(
            agent_ids=np.array([], dtype=object),
            lats=np.array([]),
            lons=np.array([]),
            edge_ids=np.array([], dtype=np.int64),
            edge_progress=np.array([]),
            route_edge_ids=np.array([], dtype=object),
            route_indices=np.array([], dtype=np.int64),
            speeds_mps=np.array([]),
            bearings_deg=np.array([]),
            start_times=np.array([]),
            elapsed_times=np.array([]),
            is_running=np.array([], dtype=bool),
            reached_destination=np.array([], dtype=bool),
            config_indices=np.array([], dtype=np.int32),
            total_distances_m=np.array([])
        )
    
    async def _load_graph_cache(self):
        """
        Load graph cache from database.
        
        Queries PostgreSQL for all edges and builds GraphCache
        (dense numpy arrays indexed by edge_id).
        """
        # Database connection parameters (TODO: from config)
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = int(os.getenv('POSTGRES_PORT', 5432))
        db_name = os.getenv('POSTGRES_DB', 'osm')
        db_user = os.getenv('POSTGRES_USER', 'postgres')
        db_password = os.getenv('POSTGRES_PASSWORD', 'postgres')
        
        try:
            # Connect to database
            import asyncpg
            conn = await asyncpg.connect(
                host=db_host,
                port=db_port,
                database=db_name,
                user=db_user,
                password=db_password
            )
            
            # Query: SELECT * FROM graphs.get_simulation_graph()
            logger.info("Loading graph from database...")
            rows = await conn.fetch(
                "SELECT * FROM graphs.get_simulation_graph()"
            )
            
            if not rows:
                logger.warning("No edges found in database")
                await conn.close()
                return
            
            # Find max edge_id
            max_edge_id = max(row['edge_id'] for row in rows)
            logger.info(f"Graph size: {len(rows)} edges, max_id={max_edge_id}")
            
            # Create dense arrays (size = max_edge_id + 1)
            speeds = np.zeros(max_edge_id + 1, dtype=np.float32)
            start_lons = np.zeros(max_edge_id + 1, dtype=np.float32)
            start_lats = np.zeros(max_edge_id + 1, dtype=np.float32)
            end_lons = np.zeros(max_edge_id + 1, dtype=np.float32)
            end_lats = np.zeros(max_edge_id + 1, dtype=np.float32)
            lengths = np.zeros(max_edge_id + 1, dtype=np.float32)
            
            # Fill arrays
            for row in rows:
                idx = row['edge_id']
                speeds[idx] = row['speed_limit_kmh']
                start_lons[idx] = row['start_lon']
                start_lats[idx] = row['start_lat']
                end_lons[idx] = row['end_lon']
                end_lats[idx] = row['end_lat']
                lengths[idx] = row['length_m']
            
            # Create GraphCache
            self.graph_cache = GraphCache(
                speeds=speeds,
                start_lons=start_lons,
                start_lats=start_lats,
                end_lons=end_lons,
                end_lats=end_lats,
                lengths=lengths
            )
            
            await conn.close()
            logger.success(f"Graph cache loaded: {len(rows)} edges")
            
        except Exception as e:
            logger.error(f"Failed to load graph cache: {e}", exc_info=e)
            # Continue without graph (for testing without DB)
    
    async def _sync_agents_to_db(self):
        """
        Sync agent positions to database (every 5 sec).
        
        Updates agents table with current positions.
        """
        if self.batch is None or self.batch.size == 0:
            return
        
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = int(os.getenv('POSTGRES_PORT', 5432))
        db_name = os.getenv('POSTGRES_DB', 'osm')
        db_user = os.getenv('POSTGRES_USER', 'postgres')
        db_password = os.getenv('POSTGRES_PASSWORD', 'postgres')
        
        try:
            import asyncpg
            conn = await asyncpg.connect(
                host=db_host,
                port=db_port,
                database=db_name,
                user=db_user,
                password=db_password
            )
            
            # Build UPDATE query (batch)
            # UPDATE agents SET lat=$1, lon=$2, edge_id=$3 WHERE agent_id=$4
            
            values = [
                (
                    float(self.batch.lats[i]),
                    float(self.batch.lons[i]),
                    int(self.batch.edge_ids[i]),
                    str(self.batch.agent_ids[i])
                )
                for i in range(self.batch.size)
            ]
            
            await conn.executemany(
                """
                UPDATE agents
                SET lat = $1, lon = $2, edge_id = $3, updated_at = NOW()
                WHERE agent_id = $4
                """,
                values
            )
            
            await conn.close()
            logger.debug(f"Synced {self.batch.size} agents to DB")
            
        except Exception as e:
            logger.warning(f"Failed to sync agents to DB: {e}")

