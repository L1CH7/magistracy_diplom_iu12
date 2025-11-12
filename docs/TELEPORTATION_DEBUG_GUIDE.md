# Teleportation Debugging Guide

## Overview

Agent teleportation debugging system with multiple validation layers:

1. **Client-side detection** (`main_window_handlers.py`)
2. **Agent-side detection** (`agent.py` in `get_current_position()`)
3. **Server-side detection** (`app.py` in `/sim/agent/{id}/position`)

## Log Levels

- **ERROR**: Teleportation detected (distance > threshold)
- **WARNING**: Route restart, consistency issues
- **INFO**: Route switches, merge operations
- **DEBUG**: Agent state snapshots (enable with `DEBUG=1` env var)

## Key Log Events

### 1. TELEPORTATION_DETECTED (Client-side)
```
[error] TELEPORTATION_DETECTED
  agent_id=1
  distance_m=894.46  # Distance between frames
  threshold_m=16.3   # Allowed threshold
  dS_critical_m=14.81
  sim_speed=8.0
  fps=30
  prev_pos=(37.57460128, 55.75301677)
  current_pos=(37.57797712, 55.76084783)
  agent_state_before={'speed_kmh': 64.19, 'route_id': 5, 'state': 'Moving'}
```

**Analysis:**
- `distance_m > threshold_m` → Teleportation!
- Check `route_id` changes → Route switch?
- Compare `prev_pos` and `current_pos` → Direction?

### 2. AGENT_TELEPORT_IN_get_current_position (Agent-side)
```
[error] AGENT_TELEPORT_IN_get_current_position
  agent_id=1
  distance_m=304.91
  expected_m=3.77  # Expected distance based on speed
  threshold_m=11.31  # 3x margin
  current_speed_mps=13.89
  sim_speed=8.0
  route_id=5
  elapsed_time=45.23
  start_time=1699814231.45
  distance_traveled=5024.87
  route_distance_m=4520.12
  overall_progress=1.1117  # PROBLEM: progress > 1.0!
```

**Analysis:**
- `distance_m >> expected_m` → Real teleportation in calculation
- `overall_progress > 1.0` → Agent went past route end!
- `distance_traveled > route_distance_m` → Time calculation wrong
- **Root cause:** `start_time` not adjusted after route merge

### 3. SERVER_DETECTED_TELEPORT (Server-side)
```
[error] SERVER_DETECTED_TELEPORT
  agent_id=1
  distance_m=217.38
  max_possible_m=8.34  # Max possible with sim_speed
  sim_speed=8.0
  route_id=10
  elapsed_time=12.45
  start_time=1699814234.12
```

**Analysis:**
- Server confirms client detection
- `distance_m` much larger than `max_possible_m`
- Check corresponding `route_switch_requested` log

### 4. route_switch_requested
```
[info] route_switch_requested
  agent_id=1
  current_route_id=5
  selected_route_id=10
  agent_edge_idx=18
  agent_progress=0.876
```

**Analysis:**
- User selected new route
- Agent at 87.6% of current route
- Check if merge logic triggered or restart

### 5. agent_RESTARTED_on_new_route
```
[warning] agent_RESTARTED_on_new_route
  agent_id=1
  old_route=5
  new_route=10
  old_start_time=1699814231.45
  new_start_time=1699814243.67
  time_diff=12.22
  reason="remaining_edges_empty"
```

**Analysis:**
- Agent restarted from beginning (not merged!)
- `reason="remaining_edges_empty"` → Agent at end of route
- This causes LARGE teleportation (to start of new route)
- **Expected:** Merge should happen if routes intersect

### 6. merge_updated_position
```
[info] merge_updated_position
  agent_id=1
  old_idx=18
  new_idx=12
  edge_id=4523
  distance_to_agent=2847.23  # Absolute distance in merged route
  elapsed_new=204.89  # Recalculated elapsed time
  start_time_adjusted=True
```

**Analysis:**
- Merge happened successfully
- `start_time` adjusted to maintain position
- `distance_to_agent` preserved from old route
- **If this log missing:** Merge didn't happen!

### 7. FATAL_merge_failed_restarting_agent
```
[error] FATAL_merge_failed_restarting_agent
  agent_id=1
  current_route=5
  selected_route=10
```

**Analysis:**
- Merge failed (current edge not in merged route)
- Agent forcefully restarted
- **Root cause:** Route merging algorithm error

## Diagnostic Commands

### 1. Check all teleportations
```bash
docker compose logs client 2>&1 | grep TELEPORTATION | tail -50
```

### 2. Check route switches
```bash
docker compose logs server 2>&1 | grep "route_switch_requested" | tail -20
```

### 3. Check restarts vs merges
```bash
docker compose logs server 2>&1 | grep -E "(RESTARTED|merge_updated_position)" | tail -30
```

### 4. Check merge failures
```bash
docker compose logs server 2>&1 | grep FATAL
```

### 5. Enable DEBUG logging
```bash
# In docker-compose.yml, add:
environment:
  - LOG_LEVEL=DEBUG

# Then restart:
docker compose up --build -d
```

### 6. Agent state snapshots (DEBUG level)
```bash
docker compose logs server 2>&1 | grep "agent_state_snapshot" | tail -20
```

## Common Patterns

### Pattern 1: Route Switch → Restart → Teleportation
```
[info] route_switch_requested (route 5 → 10)
[warning] agent_RESTARTED_on_new_route (reason: remaining_edges_empty)
[error] TELEPORTATION_DETECTED (distance: 894m)
```

**Cause:** Agent at end of route, no merge possible.  
**Fix:** Accept as expected behavior (large jump to new route start).  
**Alternative:** Add "smooth transition" by continuing to nearest point.

### Pattern 2: Route Switch → Merge → Teleportation
```
[info] route_switch_requested (route 5 → 10)
[info] merge_updated_position (start_time_adjusted=True)
[error] TELEPORTATION_DETECTED (distance: 304m)
```

**Cause:** `start_time` adjustment incorrect.  
**Fix:** Check `distance_to_agent` calculation in merge logic.

### Pattern 3: Continuous Teleportation on Same Route
```
[error] TELEPORTATION_DETECTED (distance: 17.9m, route 15)
[error] TELEPORTATION_DETECTED (distance: 18.7m, route 15)
[error] TELEPORTATION_DETECTED (distance: 17.5m, route 15)
```

**Cause:** `get_current_position()` calculation wrong.  
**Root:** `start_time` inconsistent with `route_distance_m`.

### Pattern 4: progress > 1.0
```
[error] AGENT_TELEPORT_IN_get_current_position
  overall_progress=1.1117
  distance_traveled=5024.87
  route_distance_m=4520.12
```

**Cause:** Agent traveled more than route length.  
**Root:** `start_time` too old, `elapsed_time * speed` exceeds route.

## Root Cause Analysis

### Hypothesis 1: Race Condition
- Client requests position
- Server switches route (updates `start_time`)
- Client receives position based on **old** `start_time`
- Next frame: position based on **new** `start_time`
- **Result:** Jump between old and new calculations

**Fix:** Lock route switching until next position request.

### Hypothesis 2: Incorrect start_time Adjustment
Current code:
```python
elapsed_new = distance_to_agent / (sim_speed * max_speed)
agent.start_time = time.time() - elapsed_new
```

**Problem:** Assumes constant `max_speed`, but agent has variable speed!

**Fix:** Calculate actual time based on variable speeds:
```python
# Integrate time for each edge
time_to_agent = 0.0
for i in range(new_edge_idx):
    edge = graph.get_edge(merged_edges[i])
    edge_speed = calculate_edge_speed(edge, agent)
    time_to_agent += edge.length_m / edge_speed

# Add time within current edge
edge_speed_current = calculate_edge_speed(curr_edge, agent)
time_to_agent += distance_within_edge / edge_speed_current

# Adjust start_time
elapsed_new = time_to_agent / sim_speed
agent.start_time = time.time() - elapsed_new
```

### Hypothesis 3: Merge Not Triggered
Logs show `agent_RESTARTED_on_new_route` instead of `merge_updated_position`.

**Reason:** `remaining_edges` empty → agent at route end.

**Fix:** Add lookahead or accept restart as valid behavior.

## Testing Strategy

1. **Export route cache** (see `ROUTE_CACHE_README.md`)
2. **Replay selections** in unit test
3. **Assert no teleportation** using detection logs
4. **Test edge cases:**
   - Route switch at end → restart expected
   - Route switch mid-route → merge expected
   - Non-intersecting routes → restart or error

## Next Steps

1. ✅ Add detailed logging (DONE)
2. ⏳ Analyze logs to identify dominant pattern
3. ⏳ Fix `start_time` adjustment algorithm
4. ⏳ Add unit tests with route cache
5. ⏳ Validate fix with detection disabled (performance test)

## Log Collection Script

```bash
#!/bin/bash
# collect_teleport_logs.sh

echo "=== TELEPORTATION EVENTS ==="
docker compose logs client 2>&1 | grep TELEPORTATION | tail -20

echo ""
echo "=== ROUTE SWITCHES ==="
docker compose logs server 2>&1 | grep route_switch_requested | tail -10

echo ""
echo "=== RESTARTS VS MERGES ==="
docker compose logs server 2>&1 | grep -E "(RESTARTED|merge_updated)" | tail -15

echo ""
echo "=== FATAL ERRORS ==="
docker compose logs server 2>&1 | grep FATAL
```

Save as `scripts/collect_teleport_logs.sh` and run:
```bash
chmod +x scripts/collect_teleport_logs.sh
./scripts/collect_teleport_logs.sh > teleport_report.txt
```
