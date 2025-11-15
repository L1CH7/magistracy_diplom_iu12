# RD-3: ETA Calculation & Route ID Architecture Fixes

**Date:** 2025-11-11  
**Session:** ETA debugging and route reference architecture fixes  
**Status:** ✅ Completed (Core Issues Resolved)

---

## Executive Summary

Resolved critical bugs in ETA calculation and route management architecture that caused agents to fail mid-route and display incorrect ETA. Implemented global unique route IDs and refactored ETA calculation logic to use progress-based approach instead of edge-based indices.

---

## Problems Identified

### 1. **ETA Returning 0 Mid-Route (50-70% Progress)**

**Symptom:**
- Agent reaches 50-70% of route, ETA suddenly drops to 0
- Logs show `ETA_FINISHED: returning 0` despite agent not finished
- condition: `current_edge_index >= len(route_edges)` triggering incorrectly

**Root Cause:**
```python
# BEFORE (BROKEN):
current_edge_index = agent.current_edge_index  # Computed from OLD route
if current_edge_index >= len(route_edges):  # Compared with NEW route
    return 0.0
```

When user changes routes:
1. Agent has `current_edge_index=50` from old 100-edge route
2. New route has only 20 edges
3. Condition `50 >= 20` triggers, returns ETA=0

**Example from logs:**
```
ETA_CALC: agent=2, progress=0.525, total_time=177.88
ETA_FINISHED: returning 0  # WRONG! Agent at 52.5%, not finished
```

---

### 2. **Non-Unique Route IDs Causing Agent Confusion**

**Symptom:**
- Agent continues on wrong route after points changed
- `assigned_route_id=0` matches multiple different routes
- Agent movement exceeds new route bounds

**Root Cause:**
```python
# route_builder.py
for idx, route in enumerate(routes):
    route.id = idx  # Always 0, 1, 2... EVERY time
```

Routes A→B get IDs [0,1,2], then routes C→D also get IDs [0,1,2]. Agent with `assigned_route_id=0` references WRONG route after points change.

---

### 3. **Simulation State Persistence Across Restarts**

**Symptom:**
- Old agents persist after `docker compose restart`
- `sim_agents` and `sim_routes` dicts not cleared
- Stale agent data causes route mismatches

**Root Cause:**
- No cleanup in FastAPI startup event
- `docker compose restart` doesn't recreate Python process

---

## Solutions Implemented

### 1. **ETA Uses Progress-Based Check Instead of Edge Index**

**Change:**
```python
# AFTER (FIXED):
overall_progress = agent.current_progress  # Route-independent [0.0-1.0]

if overall_progress >= 0.99:  # Check progress, not edge_index
    return 0.0

remaining_fraction = 1.0 - overall_progress
eta = total_time_sec * remaining_fraction  # Linear interpolation
```

**Benefits:**
- Works regardless of route length (10 edges or 100 edges)
- No dependency on `current_edge_index`
- Simple, predictable behavior

---

### 2. **Global Unique Route IDs**

**Change:**
```python
# app.py
next_route_id = 0  # Global counter

@app.post("/routes")
def post_routes(req: RouteRequest):
    global next_route_id
    
    for route in routes:
        route.id = next_route_id  # Globally unique
        next_route_id += 1
```

**Benefits:**
- Route IDs never repeat (0, 1, 2, 3, ..., N)
- Agent `assigned_route_id` uniquely identifies route
- No confusion when points change

---

### 3. **Simulation State Cleanup on Startup**

**Change:**
```python
@app.on_event("startup")
def startup_event():
    global sim_agents, sim_routes
    
    sim_agents.clear()
    sim_routes.clear()
    log.info("Simulation state cleared on startup")
```

**Note:** Requires `docker compose down && up` (not just `restart`)

---

## Technical Details

### ETA Calculation Algorithm

**Formula:**
```python
if progress <= 0.01:
    eta = total_time_sec  # Start: full route time
elif progress >= 0.99:
    eta = 0.0  # End: finished
else:
    eta = total_time_sec * (1 - progress)  # Linear decay
```

**Assumptions:**
- Linear progress (uniform speed distribution)
- No congestion factor yet (TODO)
- Real-time ETA (not sim-time)

---

### Route Reference Architecture

**Agent Dataclass:**
```python
@dataclass
class SimulationAgent:
    agent_id: int
    assigned_route_id: int  # Reference to route (DYNAMIC)
    current_progress: float  # [0.0-1.0] route completion
    current_edge_index: int  # For internal use only
```

**Server State:**
```python
sim_agents: Dict[int, SimulationAgent]  # agent_id -> agent
sim_routes: Dict[int, dict]  # agent_id -> route_data
route_cache: Dict[str, RouteResponse]  # cache_key -> routes
```

**Lifecycle:**
1. `/routes`: Build routes, assign global unique IDs
2. `/start`: Create agent with `assigned_route_id`, store route_data in `sim_routes[agent_id]`
3. `/position`: Lookup `route_data = sim_routes[agent_id]`, pass to `agent.get_current_position(route_data)`
4. `/restart`: Update `assigned_route_id`, replace `sim_routes[agent_id]`, call `agent.restart()`

---

## Testing & Verification

### Test Cases Verified

1. **✅ ETA on Full Route (0% → 100%)**
   - Starts at `total_time_sec`
   - Decreases linearly
   - Reaches 0 at finish

2. **✅ Route Change Mid-Movement**
   - Agent at 50% on long route (100 edges)
   - Switch to short route (20 edges)
   - Restart → ETA calculates correctly

3. **✅ Multiple Agents on Different Routes**
   - Agent 1 on route_id=0
   - Agent 2 on route_id=1
   - No cross-contamination

4. **✅ Global Route ID Uniqueness**
   - Routes A→B: IDs [0,1,2]
   - Routes C→D: IDs [3,4,5]
   - Agent references remain valid

---

## Known Limitations

1. **ETA Linear Interpolation**
   - Assumes uniform speed
   - Doesn't account for edge-specific congestion
   - TODO: Per-edge speed limits + congestion factor

2. **UI Route Visualization**
   - All routes show same color (grey)
   - TODO: Grey (all), Blue (selected), Green (agent)

3. **No Predictive Rerouting**
   - Agent doesn't auto-switch to selected route
   - TODO: Check if agent on new route edges → switch

4. **Simulation State Requires Full Restart**
   - `docker compose restart` insufficient
   - Must use `docker compose down && up`

---

## Performance Impact

- ✅ ETA calculation: O(1) instead of O(edges)
- ✅ No edge iteration in hot path
- ✅ Simple arithmetic operations

---

## Code Changes Summary

### Files Modified

1. **`src/server/app.py`**
   - Added `next_route_id` global counter
   - Refactored `calculate_eta_seconds()` (progress-based)
   - Added `sim_agents.clear()` in `startup_event()`

2. **`src/simulation/agent.py`**
   - Simplified `restart()` method
   - Removed debug logging

### Lines Changed
- `app.py`: ~50 lines (ETA function rewrite)
- `agent.py`: ~10 lines (cleanup)

---

## Lessons Learned

### Architectural Insights

1. **Avoid Derived State in Hot Paths**
   - `current_edge_index` derived from `progress` + `old_route`
   - Used in comparison with `new_route` → mismatch
   - Solution: Use source-of-truth (`overall_progress`)

2. **Global IDs for Shared Resources**
   - Route IDs scoped per-request → collisions
   - Global counter ensures uniqueness

3. **Explicit State Cleanup**
   - Python process persists across Docker restarts
   - Need explicit cleanup in startup event

### Debugging Techniques

1. **Print-Based Debugging Effective**
   - `print()` with `flush=True` more reliable than logger in loops
   - Immediate output helps identify logic flow

2. **Log Analysis Patterns**
   - Grep for specific events: `ETA_CALC`, `ETA_FINISHED`
   - Correlate `progress` with `total_edges`
   - Find discrepancies quickly

3. **User Feedback Critical**
   - User reports: "ETA=0 at 70%"
   - Logs confirm: `current_edge_index > len(route_edges)`
   - Root cause: architectural mismatch

---

## Future Work (TODO)

### Priority 1: UI Route Visualization
- Grey: All proposed routes
- Blue: Selected route (user clicked)
- Green: Agent's assigned route

### Priority 2: Congestion-Based ETA
```python
for edge_id in remaining_edges:
    edge = graph.get_edge(edge_id)
    congestion_factor = edge.current_load / edge.capacity
    effective_speed = speed_limit * (1 - congestion_factor)
    eta += edge.length / effective_speed
```

### Priority 3: Predictive Rerouting
- Check if agent's current_edge in new_route.edges
- If yes: switch `assigned_route_id`
- If no: continue old route, show both (green + blue)

### Priority 4: ETA Timer (Client-Side)
- Update ETA from server every `10 * fps` ms
- Between updates: countdown timer (decrease)
- Smooth UX without server spam

---

## Conclusion

Successfully resolved critical ETA and routing bugs through:
1. Simplified ETA logic (progress-based)
2. Global unique route IDs
3. Explicit state management

System now supports:
- ✅ Accurate ETA throughout entire route
- ✅ Multiple agents on different routes
- ✅ Route changes without agent confusion
- ✅ Restart functionality

Next phase: UI enhancements (route colors) and advanced features (predictive rerouting, congestion).

---

**Session Duration:** ~4 hours  
**Commits:** Multiple (route ID, ETA refactor, startup cleanup)  
**Status:** Ready for UI development phase
