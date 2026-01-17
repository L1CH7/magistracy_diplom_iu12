# Agent System - Usage Guide

## Overview

Новая архитектура агента состоит из:

1. **Pure Data** - `AgentState`, `AgentConfig` (immutable dataclasses)
2. **Pure Functions** - `move()`, `detect_teleport()`, `can_switch_route()` (no side effects)
3. **Batch Operations** - `AgentBatch`, `move_batch()` (numpy vectorization)
4. **Config Management** - YAML конфиги вместо хардкода

---

## Single Agent Usage (для тестирования)

```python
from src.shared.models.agent import AgentState
from src.shared.agent import move, get_agent_config_manager

# Load config from YAML
config_manager = get_agent_config_manager()
car_config = config_manager.get_config('car_normal')

# Create agent state
state = AgentState(
    agent_id='agent_1',
    lat=55.751,
    lon=37.618,
    edge_id=42,
    edge_progress=0.0,
    route_edge_ids=[42, 43, 44],
    route_index=0,
    current_speed_mps=0.0,
    bearing_degrees=0.0,
    start_time=time.time(),
    elapsed_time=0.0,
    is_running=True,
    reached_destination=False,
    config=car_config
)

# Prepare graph data (Dict lookups - not optimal for 1000 agents)
edge_speeds = {42: 60.0, 43: 40.0, 44: 50.0}  # km/h
edge_geometries = {
    42: ((37.618, 55.751), (37.620, 55.752)),
    43: ((37.620, 55.752), (37.622, 55.753)),
    44: ((37.622, 55.753), (37.624, 55.754))
}
turn_angles = {
    (42, 43): 45.0,  # 45° turn
    (43, 44): 10.0   # slight turn
}

# Simulation loop (20 FPS)
dt = 0.05  # 50ms per tick
for tick in range(200):  # 10 seconds
    new_state = move(
        state,
        dt,
        edge_speeds,
        edge_geometries,
        turn_angles
    )
    
    print(f"Tick {tick}: pos=({new_state.lat:.6f}, {new_state.lon:.6f}), "
          f"speed={new_state.current_speed_mps:.1f}m/s")
    
    state = new_state
    
    if state.reached_destination:
        print("Agent reached destination!")
        break
```

---

## Batch Operations (для 1000 агентов)

```python
import numpy as np
from src.shared.agent import (
    AgentBatch,
    GraphCache,
    move_batch,
    get_agent_config_manager
)

# Prepare graph cache (precomputed arrays for fast lookup)
# This is done ONCE at startup
max_edge_id = 10000
graph = GraphCache(
    max_edge_id=max_edge_id,
    edge_speeds={i: 50.0 for i in range(1, max_edge_id)},
    edge_start_points={i: (37.6 + i*0.0001, 55.7) for i in range(1, max_edge_id)},
    edge_end_points={i: (37.6 + i*0.0001, 55.8) for i in range(1, max_edge_id)},
    edge_lengths={i: 100.0 for i in range(1, max_edge_id)}
)

# Optional: transfer to GPU (if CuPy available)
# graph = graph.to_gpu()

# Create batch of 1000 agents
n_agents = 1000
batch = AgentBatch(
    agent_ids=np.array([f"agent_{i}" for i in range(n_agents)], dtype=object),
    lats=np.random.uniform(55.75, 55.76, n_agents),
    lons=np.random.uniform(37.61, 37.62, n_agents),
    edge_ids=np.random.randint(1, 1000, n_agents, dtype=np.int64),
    edge_progress=np.zeros(n_agents),  # all start at edge beginning
    route_edge_ids=np.array(
        [[i, i+1, i+2] for i in range(1, n_agents+1)],
        dtype=object
    ),
    route_indices=np.zeros(n_agents, dtype=np.int64),
    speeds_mps=np.zeros(n_agents),
    bearings_deg=np.zeros(n_agents),
    start_times=np.full(n_agents, time.time()),
    elapsed_times=np.zeros(n_agents),
    is_running=np.ones(n_agents, dtype=bool),
    reached_destination=np.zeros(n_agents, dtype=bool),
    config_indices=np.zeros(n_agents, dtype=np.int32),  # all use same config
    total_distances_m=np.zeros(n_agents)
)

# Simulation loop @ 20 FPS
dt = 0.05
use_gpu = False  # Set True if GPU available

for tick in range(200):
    # Update all 1000 agents at once (< 5ms on CPU!)
    batch = move_batch(batch, dt, graph, use_gpu=use_gpu)
    
    # Get running agents
    n_running = batch.is_running.sum()
    
    if tick % 20 == 0:  # Every second
        print(f"Second {tick//20}: {n_running} agents running")
    
    if n_running == 0:
        print("All agents reached destination!")
        break

# Results
completed = batch.reached_destination.sum()
print(f"Completed: {completed}/{n_agents}")
print(f"Avg distance: {batch.total_distances_m.mean():.1f}m")
```

---

## Config Management

### Load preset configs

```python
from src.shared.agent import get_agent_config_manager

manager = get_agent_config_manager()

# Get preset configs
car_normal = manager.get_config('car_normal')
car_hurry = manager.get_config('car_hurry')
emergency = manager.get_config('emergency')
truck = manager.get_config('truck')

print(car_normal.driver_speed_factor)  # 0.92 (drives at 92% of limit)
print(emergency.priority)  # 20
print(truck.max_speed_override_kmh)  # 70 (limited to 70 km/h)
```

### Create custom config

```python
# Based on preset with overrides
custom_fast_car = manager.create_custom(
    base='car_normal',
    priority=10,  # special priority
    driver_speed_factor=0.98,  # drive faster
    max_speed_override_kmh=90
)
```

### Speed margin calculation

```python
# Russia: speed_limit + 19 km/h
edge_speed = 60  # km/h
max_allowed = manager.calculate_max_allowed_speed(edge_speed, region='russia')
print(max_allowed)  # 79 km/h

# Turkey: speed_limit * 1.1
max_allowed = manager.calculate_max_allowed_speed(edge_speed, region='turkey')
print(max_allowed)  # 66 km/h

# Europe: strict limit
max_allowed = manager.calculate_max_allowed_speed(edge_speed, region='europe')
print(max_allowed)  # 60 km/h
```

---

## Teleport Detection

```python
from src.shared.agent import detect_teleport

# For single agent
prev_state = ...  # previous state
new_state = move(prev_state, dt, ...)

alert = detect_teleport(prev_state, new_state, dt)
if alert:
    print(f"TELEPORT detected! Expected {alert.expected_distance_m:.1f}m, "
          f"actual {alert.actual_distance_m:.1f}m")

# For batch (vectorized)
from src.shared.agent import detect_teleports_batch

teleports = detect_teleports_batch(
    prev_batch.lats,
    prev_batch.lons,
    new_batch.lats,
    new_batch.lons,
    max_speeds_mps=np.full(n_agents, 20.0),
    dt=dt
)

teleport_indices = np.where(teleports)[0]
print(f"Detected {len(teleport_indices)} teleports")
```

---

## Route Switching

```python
from src.shared.agent import can_switch_route

# Check if agent can switch to new route
new_route = [45, 46, 47, 48]  # new edge IDs
graph_edges = {
    42: (100, 101),  # edge 42: node 100 → 101
    43: (101, 102),
    44: (102, 103),
    45: (101, 104),  # overlaps at node 101
    ...
}

can_switch, new_index = can_switch_route(
    state,
    tuple(new_route),
    graph_edges
)

if can_switch:
    # Switch route at intersection
    state = AgentState(
        **{
            **state.__dict__,
            'route_edge_ids': new_route,
            'route_index': new_index
        }
    )
    print(f"Switched to new route at edge {new_route[new_index]}")
else:
    print("Cannot switch - no overlap with current route")
```

---

## Performance Benchmarks

```python
from src.shared.agent import benchmark_batch_movement

# Benchmark batch operations
benchmark_batch_movement(n_agents=1000, n_iterations=100)

# Expected output:
# === Agent Batch Movement Benchmark ===
#
# Numba available: True
# GPU available: False
#
# Benchmarking 1000 agents, 100 ticks...
# Results:
#   Total time: 0.42s
#   Avg time per tick: 4.20ms
#   Theoretical max FPS: 238.1
#   Updates per second: 238095
# ✅ PASS: < 5ms per tick
```

---

## Integration with Simulation Service

```python
# In services/simulation/src/manager.py

from src.shared.agent import (
    AgentBatch,
    GraphCache,
    move_batch,
    get_agent_config_manager
)

class SimulationManager:
    def __init__(self):
        self.batch = None
        self.graph_cache = None
        self.config_manager = get_agent_config_manager()
        
    async def initialize_graph(self, graph_data):
        """Load graph into cache (once at startup)."""
        self.graph_cache = GraphCache(
            max_edge_id=graph_data['max_edge_id'],
            edge_speeds=graph_data['speeds'],
            edge_start_points=graph_data['start_points'],
            edge_end_points=graph_data['end_points'],
            edge_lengths=graph_data['lengths']
        )
    
    async def add_agent(self, agent_id, route, agent_type='car_normal'):
        """Add agent to batch."""
        config = self.config_manager.get_config(agent_type)
        
        # Add to batch (grow arrays)
        # TODO: implement batch growth
        
    async def tick(self):
        """Update all agents (called 20 times per second)."""
        if self.batch is None:
            return
        
        dt = 1.0 / 20  # 0.05s
        self.batch = move_batch(self.batch, dt, self.graph_cache)
        
        # Broadcast positions to Coordinator
        await self.broadcast_positions()
```

---

## Config Files

`configs/simulation/agent_physics.yaml`:
- Agent type presets (car_normal, car_hurry, emergency, truck)
- Speed penalty regions (russia, turkey, belarus, europe)
- Physics parameters (accel zones, turn thresholds)
- Teleport detection settings

Edit this file to tweak agent behavior WITHOUT code changes!
Hot reload supported.

---

## GPU Acceleration

If CuPy installed:

```bash
pip install cupy-cuda11x  # for CUDA 11.x
# or
pip install cupy-cuda12x  # for CUDA 12.x
```

Then:

```python
# Transfer graph to GPU
graph = graph.to_gpu()

# Use GPU in move_batch
batch = move_batch(batch, dt, graph, use_gpu=True)
```

Expected speedup: 3-5x for 1000+ agents.

---

## Docker Considerations

GPU not available in standard Docker containers. Fallback to CPU automatic.

For GPU support in Docker:

```yaml
# docker-compose.yml
services:
  simulation:
    build: ./services/simulation
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Requires: nvidia-docker runtime.

For most cases, CPU (with Numba JIT) is sufficient for 1000 agents @ 20 FPS.
