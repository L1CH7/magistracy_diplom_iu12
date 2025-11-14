# TODO: System Improvements

## Critical (Architecture)

### 1. Refactor Agent to Route Reference
**Priority**: P0 - CRITICAL  
**Location**: `src/simulation/agent.py`, `src/server/app.py`

**Current Problem**:
```python
# BAD: Agent stores snapshot
agent.route_edges = [101, 102, ...]
agent.route_coords = [(lon, lat), ...]
```

**Required**:
```python
# GOOD: Agent references route dynamically
agent.assigned_route_id = 42
agent.current_edge_index = 5

# Get route dynamically:
route = route_cache.get(agent.assigned_route_id)
```

**Benefits**:
- Enables dynamic rerouting without agent deletion
- Supports 1000+ agents with shared routes
- Foundation for congestion simulation

**Files to modify**:
- `src/simulation/agent.py`: Change dataclass fields
- `src/server/app.py`: Update all endpoints to query route_cache
- `src/client/ui/main_window_handlers.py`: No client changes needed

**Estimated Effort**: 2-3 hours

---

### 2. Implement Mid-Route Rerouting
**Priority**: P0 - CRITICAL  
**Location**: `src/server/app.py` - new endpoint

**New Endpoint**: `POST /sim/agent/{id}/reroute`
```json
Request:
{
  "new_route_id": 43,
  "reason": "congestion_ahead"
}

Response:
{
  "agent_id": 1,
  "old_route_id": 42,
  "new_route_id": 43,
  "switched": true,
  "message": "Agent switched to new route at edge 105"
}
```

**Logic**:
```python
def reroute_agent(agent_id, new_route_id):
    agent = sim_agents[agent_id]
    new_route = route_cache[new_route_id]
    
    # Check if agent on new route
    if agent.current_edge_id in new_route.edge_ids:
        # Switch immediately
        agent.assigned_route_id = new_route_id
        agent.current_edge_index = new_route.edge_ids.index(agent.current_edge_id)
        return {"switched": True}
    
    # Check if can switch at next intersection
    for i, edge in enumerate(new_route.edge_ids):
        if edges_connected(agent.current_edge_id, edge):
            agent.pending_route_id = new_route_id
            agent.switch_at_edge = edge
            return {"switched": False, "pending": True}
    
    return {"switched": False, "error": "Agent too far off route"}
```

**Estimated Effort**: 3-4 hours

---

## High Priority (Simulation)

### 3. Track Edge Load (Congestion)
**Priority**: P1 - HIGH  
**Location**: `src/routing/graph.py`, `src/server/app.py`

**Requirements**:
- Track `current_load` for each edge (number of agents on edge)
- Update `effective_speed_kmh` based on load/capacity ratio
- Persist in PostgreSQL `edges` table (already has columns!)

**Implementation**:
```python
# When agent enters edge:
def agent_enter_edge(agent_id, edge_id):
    edge = graph.edges[edge_id]
    edge.current_load += 1
    
    # Update effective speed
    if edge.current_load > edge.capacity:
        congestion_factor = edge.current_load / edge.capacity
        edge.effective_speed_kmh = edge.speed_limit_kmh / (1 + 0.5 * (congestion_factor - 1))
    
    # Persist to database
    db.update_edge_load(edge_id, edge.current_load, edge.effective_speed_kmh)

# When agent leaves edge:
def agent_leave_edge(agent_id, edge_id):
    edge = graph.edges[edge_id]
    edge.current_load -= 1
    update_effective_speed(edge)
    db.update_edge_load(edge_id, edge.current_load, edge.effective_speed_kmh)
```

**Database**:
```sql
-- Already exists in edges table:
current_load INT DEFAULT 0
effective_speed_kmh DOUBLE PRECISION
last_updated TIMESTAMP
```

**Estimated Effort**: 2-3 hours

---

### 4. Predictive Congestion Detection
**Priority**: P1 - HIGH  
**Location**: `src/coordination/` (new module)

**Requirements**:
- Monitor edge loads every 1 second
- Forecast congestion 20-60 seconds ahead
- Identify agents whose routes will hit congestion
- Trigger rerouting for affected agents

**Implementation**:
```python
# New module: src/coordination/congestion_monitor.py
class CongestionMonitor:
    def __init__(self, graph, lookahead_seconds=20):
        self.graph = graph
        self.lookahead = lookahead_seconds
    
    def detect_congestion(self):
        """Find edges approaching capacity."""
        congested_edges = []
        
        for edge_id, edge in self.graph.edges.items():
            if edge.current_load > edge.capacity * 0.8:
                congested_edges.append((edge_id, edge.current_load / edge.capacity))
        
        return congested_edges
    
    def forecast_congestion(self, edge_id):
        """Predict future load on edge."""
        # Count agents heading towards this edge
        agents_approaching = 0
        for agent in sim_agents.values():
            route = route_cache[agent.assigned_route_id]
            if edge_id in route.edge_ids[agent.current_edge_index:]:
                # Agent will reach this edge
                time_to_reach = estimate_time_to_edge(agent, edge_id)
                if time_to_reach < self.lookahead:
                    agents_approaching += 1
        
        return agents_approaching
```

**Estimated Effort**: 4-5 hours

---

## Medium Priority (Data)

### 5. OSM Incremental Tile Downloads
**Priority**: P2 - MEDIUM  
**Location**: `src/server/app.py` - `POST /osm/fetch_road_graph`

**Current Issue**: Returns cached bbox instead of downloading missing tiles.

**Required Implementation**:
```python
def fetch_incremental_tiles(bbox):
    """Download only missing OSM tiles for bbox."""
    
    # 1. Calculate tile coverage
    tiles_needed = calculate_tile_coverage(bbox)
    
    # 2. Query database for existing tiles
    existing_tiles = db.get_tiles_in_bbox(bbox)
    
    # 3. Identify missing tiles
    missing_tiles = set(tiles_needed) - set(existing_tiles)
    
    if not missing_tiles:
        log.info("All tiles cached", tiles=len(tiles_needed))
        return load_from_cache(bbox)
    
    # 4. Download missing tiles from Overpass
    log.info("Downloading missing tiles", count=len(missing_tiles))
    for tile in missing_tiles:
        osm_data = download_overpass_tile(tile)
        process_and_store_tile(osm_data)
    
    # 5. Merge with existing data
    full_graph = load_from_cache(bbox)
    return full_graph
```

**Benefits**:
- Faster: Reuse existing tiles
- No duplicates
- Expandable coverage

**Estimated Effort**: 5-6 hours

---

### 6. Route Cache Memory Management
**Priority**: P2 - MEDIUM  
**Location**: `src/server/app.py`

**Current Issue**: `route_cache` dict grows unbounded.

**Required**:
```python
from collections import OrderedDict

class LRURouteCache:
    def __init__(self, max_size=1000):
        self.cache = OrderedDict()
        self.max_size = max_size
    
    def get(self, route_id):
        if route_id in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(route_id)
            return self.cache[route_id]
        return None
    
    def set(self, route_id, route):
        if route_id in self.cache:
            self.cache.move_to_end(route_id)
        self.cache[route_id] = route
        
        # Evict oldest if over limit
        if len(self.cache) > self.max_size:
            oldest = next(iter(self.cache))
            del self.cache[oldest]
```

**Estimated Effort**: 1-2 hours

---

## Low Priority (Polish)

### 7. Agent State Persistence
**Priority**: P3 - LOW  
**Location**: `src/server/app.py`

**Current Issue**: Agents lost on server restart (in-memory only).

**Required**:
```python
# Store in Redis or PostgreSQL
import redis
r = redis.Redis()

def save_agent_state(agent):
    r.hset(f"agent:{agent.id}", mapping={
        "assigned_route_id": agent.assigned_route_id,
        "current_edge_index": agent.current_edge_index,
        "sim_speed": agent.sim_speed,
        "state": agent.state
    })

def restore_agents():
    """Called on server startup."""
    for key in r.scan_iter("agent:*"):
        agent_data = r.hgetall(key)
        agent = SimulationAgent(**agent_data)
        sim_agents[agent.id] = agent
```

**Estimated Effort**: 3-4 hours

---

### 8. Multi-Client Support
**Priority**: P3 - LOW  
**Location**: `src/server/app.py`

**Current Issue**: One global route_cache and sim_agents dict.

**Required**:
- Session-based agent storage: `sim_agents[session_id][agent_id]`
- Session cleanup after inactivity
- WebSocket for real-time updates

**Estimated Effort**: 6-8 hours

---

### 9. Performance Optimization
**Priority**: P3 - LOW  
**Location**: Various

**Targets**:
- GET /sim/agent/{id}/position: < 5ms (currently ~1.5ms ✓)
- Rerouting decision: < 100ms for 1000 agents
- Position updates: Batch updates every frame instead of per-agent

**Estimated Effort**: 4-5 hours

---

## Testing TODO

### Unit Tests Needed
- [ ] Agent route reference logic
- [ ] Edge matching algorithm
- [ ] Congestion calculation formula
- [ ] Rerouting decision logic
- [ ] LRU cache eviction

### Integration Tests Needed
- [ ] 10 agents on same route (shared reference)
- [ ] Congestion triggers rerouting
- [ ] Agent switches mid-route
- [ ] OSM incremental download

### Performance Tests Needed
- [ ] 1000 agents simultaneous position update
- [ ] Congestion detection at scale
- [ ] Route cache memory usage
- [ ] Database query performance

---

## Summary by Priority

**P0 - CRITICAL (Architecture)**:
1. Refactor Agent to Route Reference (2-3h)
2. Implement Mid-Route Rerouting (3-4h)

**P1 - HIGH (Simulation)**:
3. Track Edge Load (2-3h)
4. Predictive Congestion Detection (4-5h)

**P2 - MEDIUM (Data)**:
5. OSM Incremental Tiles (5-6h)
6. Route Cache LRU (1-2h)

**P3 - LOW (Polish)**:
7. Agent State Persistence (3-4h)
8. Multi-Client Support (6-8h)
9. Performance Optimization (4-5h)

**Total Estimated Effort**: 31-45 hours

---

**Document Created**: 2025-11-11  
**Status**: Active TODO List  
**Branch**: R-D-1
