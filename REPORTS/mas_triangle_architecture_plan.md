# MAS Triangle Architecture Plan

## Problem Statement

**Current**: Server manages all 1000+ agents, does intersection checks (ST_Intersects), route merging
**Issue**: 
- Tonna requests to server for each agent's decision
- ST_Intersects only on server side (PostGIS)
- Not scalable to 1000+ agents

**Goal**: 
- Agent as separate entity (autonomous decision-making)
- GUI client interacts with Agent AND Server (triangle)
- Coordinator (server) broadcasts routes to specific agents
- Agents auto-accept routes if intersecting + can maneuver
- Support scenarios:
  - 1 GUI per 1 agent (navigator app)
  - 1 admin GUI for all agents (monitoring dashboard)

## Proposed Architecture

```
         ┌─────────────┐
         │   Server    │
         │(Coordinator)│
         └──────┬──────┘
                │
       ┌────────┴────────┐
       │                 │
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Agent 1...N  │  │  GUI Client  │
│(Autonomous)  │◄─┤(Visualization)│
└──────────────┘  └──────────────┘
```

### Components

#### 1. Agent (Autonomous Entity)
**Location**: `src/simulation/agent.py` (already exists)

**Responsibilities**:
- Own state: position, speed, route, edges
- Decision-making: can_switch_to_route() logic
- Route merging: pre_intersecting + intersecting + post_intersecting
- Movement simulation: get_current_position()

**New Methods**:
```python
class SimulationAgent:
    def receive_route_proposal(self, route_data: dict) -> bool:
        """
        Coordinator proposes new route, agent decides to accept.
        
        Returns:
            True if accepted and merged, False if rejected
        """
        # Check intersection
        intersecting = self._find_intersecting_edges(route_data)
        
        if not intersecting:
            return False  # No overlap, reject
        
        # Check if can maneuver (time to switch lanes, etc)
        if not self._can_maneuver(intersecting[0]):
            return False  # Too late to switch
        
        # Accept and merge
        merged_route = self._merge_routes(self.route, route_data, intersecting)
        self.route = merged_route
        return True
    
    def _find_intersecting_edges(self, new_route: dict) -> List[int]:
        """Find common edges between current and new route."""
        remaining = self.route['edges'][self.current_edge_index:]
        new_edges = new_route['edges']
        return [e for e in remaining if e in new_edges]
    
    def _can_maneuver(self, first_intersect_edge: int) -> bool:
        """Check if enough time to switch to new route."""
        # Calculate time to reach first intersect edge
        # If < 2 seconds → too late
        pass
    
    def _merge_routes(self, old, new, intersecting) -> dict:
        """Create merged route: pre + intersecting + post."""
        # Already implemented in server, move here
        pass
```

**API** (if agents are separate processes):
- `POST /agent/{id}/propose_route` - coordinator sends route proposal
- `GET /agent/{id}/position` - get agent's current position
- `GET /agent/{id}/state` - get full state (for monitoring)

#### 2. Server (Coordinator)
**Location**: `src/server/app.py`

**Responsibilities**:
- Global optimization: k-routes calculation
- Route broadcasting: send proposals to specific agents
- Monitoring: collect agent states for admin GUI
- Graph management: load from PostGIS

**Changes**:
```python
# Remove intersection check from position endpoint
# Add new endpoint for route proposals

@app.post("/coordinator/broadcast_route")
async def broadcast_route(req: RouteBroadcastRequest):
    """
    Broadcast route to specific agents.
    
    Coordinator decides which agents should receive this route
    based on global optimization (congestion, ETA improvement).
    """
    target_agents = req.agent_ids
    route_data = req.route
    
    accepted_agents = []
    for agent_id in target_agents:
        # Send to agent (if separate process)
        # OR call agent.receive_route_proposal() directly
        agent = sim_agents[agent_id]
        if agent.receive_route_proposal(route_data):
            accepted_agents.append(agent_id)
    
    return {"accepted": accepted_agents}

@app.get("/coordinator/agents_state")
async def get_all_agents_state():
    """Get state of all agents for admin GUI."""
    return {
        agent_id: {
            "position": agent.get_current_position(...),
            "route_id": agent.assigned_route_id,
            "eta": agent.eta,
            "state": "Moving" if agent.is_running else "Stopped"
        }
        for agent_id, agent in sim_agents.items()
    }
```

#### 3. GUI Client
**Location**: `src/client/`

**Responsibilities**:
- Visualization: map, routes, agent position
- User interaction: click points, request routes
- Communication: with Server AND Agent

**Two Modes**:

**Mode 1: Single Agent Navigator**
```python
# Client talks to 1 agent directly
agent_api = AgentAPIClient(agent_id=1)
server_api = ServerAPIClient()

# Get routes from server
routes = server_api.get_k_routes(points, k=5)

# User selects route → send to agent
selected_route = routes[2]
agent_api.propose_route(selected_route)

# Update position
position = agent_api.get_position()
map_widget.update_agent(position)
```

**Mode 2: Admin Dashboard (1000+ agents)**
```python
# Client talks to server for all agents
server_api = ServerAPIClient()

# Get all agents state
agents_state = server_api.get_all_agents_state()

# Render all agents on map
for agent_id, state in agents_state.items():
    map_widget.draw_agent(agent_id, state['position'])

# Coordinator proposes routes
server_api.broadcast_route(
    route=optimized_route,
    agent_ids=[1, 5, 10, 20]  # affected agents
)
```

## Implementation Plan

### Phase 1: Move Logic to Agent ✅ (Partially Done)
- [x] can_switch_to_route() in agent.py
- [ ] Move route merging to agent
- [ ] Add receive_route_proposal()
- [ ] Add _can_maneuver() check

### Phase 2: Server as Coordinator
- [ ] Remove intersection check from /sim/agent/{id}/position
- [ ] Add POST /coordinator/broadcast_route
- [ ] Add GET /coordinator/agents_state
- [ ] Test with 10 agents

### Phase 3: Agent as Separate Process (Optional)
- [ ] Create AgentService (FastAPI microservice)
- [ ] Communication: gRPC or HTTP
- [ ] Load balancing: multiple agent processes
- [ ] Scale test: 1000+ agents

### Phase 4: GUI Modes
- [ ] Mode 1: Single agent navigator (current)
- [ ] Mode 2: Admin dashboard (new)
- [ ] Add mode switch in UI

## Performance Considerations

**Intersection Check**:
- Option 1: Pre-calculate edge adjacency matrix (O(1) lookup)
- Option 2: Cache intersections for common routes
- Option 3: Agent stores edge IDs in hashmap (O(1) membership)

**Route Broadcasting**:
- Use pub/sub pattern (Redis, RabbitMQ)
- Agents subscribe to routes for their region
- Coordinator publishes once, N agents receive

**Monitoring**:
- WebSocket for real-time updates
- Admin GUI polls /coordinator/agents_state every 100ms
- Aggregate metrics (avg speed, congestion) sent less frequently

## Status

- ❌ Not implemented yet
- 📝 Documented in plan
- ⏳ High priority for 1000+ agents scenario
- 🚀 Foundation exists (agent.py has logic)

## Next Steps

1. Fix teleportation bug (current session)
2. Move route merging to agent.receive_route_proposal()
3. Test with 10 agents before scaling to 1000+
4. Implement coordinator/broadcast_route
5. Build admin GUI mode

---

**Decision**: This is complex but necessary for true MAS. Implement incrementally:
- Phase 1 (now): Move logic to agent
- Phase 2 (next): Coordinator endpoints
- Phase 3 (later): Separate agent processes
- Phase 4 (future): Admin GUI mode
