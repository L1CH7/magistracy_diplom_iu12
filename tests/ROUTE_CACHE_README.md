# Route Selection Cache for Unit Tests

## Purpose

Cache of user's route selections during simulation for automated validation.

## Usage

### During Simulation

Route selections are automatically cached when you select a route in UI:

```python
# Automatically cached on route selection:
{
  "timestamp": 1699876543.123,
  "route_id": 42,
  "route_data": {
    "id": 42,
    "edges": [101, 102, 103, ...],
    "geometry": [[37.568, 55.750], ...],
    "total_distance_m": 1234.56,
    "total_time_sec": 123.4
  },
  "agent_id": 1
}
```

### Save Cache

In Python console or after simulation:

```python
# In main window instance
window.save_route_cache_for_tests("route_cache.json")
```

Or add button to UI:

```python
# In sidebar
cache_btn = QPushButton("Save Route Cache")
cache_btn.clicked.connect(lambda: self.save_route_cache_for_tests())
```

### Use in Tests

```python
import json

def test_route_switching():
    """Test that agent switches routes correctly based on recorded selections."""
    
    # Load cache
    with open("route_cache.json") as f:
        selections = json.load(f)
    
    for selection in selections:
        route_id = selection["route_id"]
        route_data = selection["route_data"]
        timestamp = selection["timestamp"]
        
        # Replay selection
        agent.receive_route_proposal(route_data)
        
        # Validate behavior
        assert agent.assigned_route_id == route_id
        assert not detect_teleportation(agent)
```

## Teleportation Detection

### Configuration

`src/client/config/simulation_config.py`:

```python
debug_teleportations: bool = True  # Enable detection
agent_max_speed_theoretical_kmh: float = 200.0  # Max speed
teleport_threshold_multiplier: float = 1.1  # 10% margin
```

### Formula

```
dS_critical = v_max * dt
dt = sim_speed / fps
v_max = 200 km/h = 55.56 m/s

Example:
sim_speed = 10x
fps = 30
dt = 10 / 30 = 0.333 sec
dS_critical = 55.56 * 0.333 = 18.5 meters
threshold = 18.5 * 1.1 = 20.35 meters

If distance > 20.35m in one frame → TELEPORTATION
```

### Detection

Automatic on every position update:

```python
def _check_teleportation(position, agent_data):
    distance = haversine(prev_pos, current_pos)
    
    if distance > threshold:
        log.error("TELEPORTATION_DETECTED",
            distance_m=distance,
            threshold_m=threshold,
            prev_pos=prev_pos,
            current_pos=current_pos,
            agent_state=agent_data
        )
```

### Logs

Check logs for teleportation events:

```bash
docker logs diplom-client-1 | grep TELEPORTATION_DETECTED
```

Example output:

```
[2025.11.12 15:30:45] ERROR TELEPORTATION_DETECTED
  agent_id=1
  distance_m=45.3
  threshold_m=20.35
  dS_critical_m=18.5
  sim_speed=10
  fps=30
  prev_pos=[37.568, 55.750]
  current_pos=[37.569, 55.751]
  agent_state_before={speed_kmh: 45.0, route_id: 42, state: "Moving"}
```

## Test Scenarios

### 1. Route Merge Test

```python
def test_route_merge_no_teleport():
    """Agent should merge routes without teleporting."""
    
    # Load cache with merge event
    selections = load_cache_with_merge()
    
    for sel in selections:
        agent.receive_route_proposal(sel["route_data"])
        
        # Check no teleportation
        assert agent.position_delta < threshold
```

### 2. Non-Intersecting Route Test

```python
def test_non_intersecting_route_rejected():
    """Agent should reject routes that don't intersect."""
    
    # Create route that doesn't intersect
    non_intersecting = create_disjoint_route()
    
    result = agent.receive_route_proposal(non_intersecting)
    
    # Should be rejected
    assert result == False
    assert agent.assigned_route_id == old_route_id
```

### 3. Lookahead Test

```python
def test_lookahead_prevents_late_switch():
    """Agent should reject switch if already passed intersection."""
    
    # Position agent 1 second before intersection
    agent.position = intersection_minus_1sec
    
    result = agent.receive_route_proposal(new_route)
    assert result == True  # Can still switch
    
    # Position agent 6 seconds past intersection
    agent.position = intersection_plus_6sec
    
    result = agent.receive_route_proposal(new_route)
    assert result == False  # Too late
```

## Performance Impact

When `debug_teleportations = False`:
- Zero overhead (branch not entered)
- Use in production with 1000+ agents

When `debug_teleportations = True`:
- ~0.1ms per frame per agent
- Acceptable for development/testing

## Future Improvements

1. **Replay mode**: Load cache and replay selections automatically
2. **Visual diff**: Show teleportation events on map
3. **Test generator**: Auto-generate unit tests from cache
4. **Regression tracking**: Compare cache across versions

---

**Status**: Implemented ✅  
**Config**: `src/client/config/simulation_config.py`  
**Detection**: `src/client/ui/main_window_handlers.py:_check_teleportation()`  
**Cache**: `src/client/ui/main_window_handlers.py:save_route_cache_for_tests()`
