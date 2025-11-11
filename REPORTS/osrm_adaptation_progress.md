# OSRM Adaptation Progress - 2025.11.11

## Completed Tasks

### 1. OSRM Profile Implementation ✅

**Created Files:**
- `configs/car_profile.yaml` (280 lines)
- `src/data/osrm_profile.py` (289 lines)
- `tests/test_osrm_profile.py` (180 lines)

**Features:**
- Complete YAML configuration with 40+ country-specific maxspeed entries
- Russian maxspeed support: ru:living_street=20, ru:urban=60, ru:motorway=110
- Speed tolerance: 20% overspeeding allowed (нештрафуемый предел)
- Profile methods:
  * `get_speed()` - highway speeds with service/surface/tracktype/smoothness penalties
  * `get_turn_penalty()` - 0-20 seconds based on angle (u-turn can be blocked)
  * `is_highway_allowed()` - filter roads by type, avoid tags, access restrictions
  * `parse_maxspeed()` - handles integers, units (mph→kmh), country-specific (ru:urban)

**Test Results:**
- 12 tests passed (highway speeds, maxspeed override, service penalties, turn penalties, highway filtering, maxspeed parsing)

---

### 2. OSM Way Processor ✅

**Created Files:**
- `src/data/osm_way_processor.py` (217 lines)

**Features:**
- Process OSM ways OSRM-style into directed graph segments
- `ProcessedSegment` dataclass with all attributes (bearing, speed, distance, travel time)
- Oneway handling (forward/reverse/bidirectional)
- Bearing calculation for turn penalties (0-360°, north=0, clockwise)
- Uses CarProfile for speed calculation and filtering
- Haversine distance calculation

**Usage:**
```python
processor = OSMWayProcessor(profile)
segments = processor.process_way(osm_way, nodes_dict)
# Returns List[ProcessedSegment] with directed edges
```

---

### 3. Turn Restrictions Manager ✅

**Created Files:**
- `src/data/turn_restrictions.py` (200 lines)

**Features:**
- Load OSM relations with type=restriction
- Parse members: from (way), via (node), to (way)
- Support prohibitive restrictions: no_left_turn, no_right_turn, no_u_turn, etc.
- Support mandatory restrictions: only_straight_on, only_left_turn, etc.
- Indexed lookup: O(1) check by (from_way, via_node)
- `is_turn_allowed()` method for A* integration

**Usage:**
```python
manager = TurnRestrictionManager()
manager.load_from_osm_relations(osm_relations)
allowed = manager.is_turn_allowed(from_way_id, via_node_id, to_way_id)
```

---

### 4. A* with Turn Penalties ✅

**Modified Files:**
- `src/routing/pathfinding.py` (384 lines)

**Features:**
- Updated `astar()` with `use_turn_penalties` parameter
- State: (node_id, prev_edge_id) to track incoming direction
- Turn penalty calculation using bearing difference
- Fast path for simple A* (when turn_penalties=False)
- Updated `k_shortest_paths()` to support turn penalties

**Performance:**
- Original A*: State = node_id → O(V + E log V)
- Turn-aware A*: State = (node_id, edge_id) → O(V*E + E² log(V*E))
- Use turn penalties only when necessary (K routes for user, not simulation)

---

## Implementation Summary

**Dependencies Installed:**
- structlog==25.5.0 (for Grafana logging)
- PyYAML==6.0.3 (for YAML configs)

**OSRM Repository Cloned:**
- Location: `.agent/osrm-backend/`
- Studied files: car.lua, way_handlers.lua, relations.lua

**Configuration System:**
- Flexible YAML-based profile (as user requested: "максимально делай конфиги в удобном формате")
- All OSRM tables extracted (as user requested: "я бы взял весь этот конфиг с его таблицами")
- Speed tolerance added (as user requested: "плюс добавим нештрафуемый предел")

---

## Next Steps (To Complete User's Directive)

User's directive: **"далее, без остановки продолжай... пока мы не научимся отдавать на клиент k маршрутов"**

### Phase 2: Database Integration (In Progress)

**Pending Tasks:**
1. ❌ Update `src/data/graph_builder.py` to use OSMWayProcessor
   - Replace current way processing with processor.process_way()
   - Store bearing in edges table (bearing field already added in migration 004)
   - Store osm_way_id for turn restrictions

2. ❌ Create turn restrictions loader
   - Load from OSM relations with type=restriction
   - Store in PostgreSQL table: turn_restrictions (relation_id, restriction_type, from_way, via_node, to_way)
   - Index by (from_way, via_node) for fast lookup

3. ❌ Update `src/routing/graph.py` Edge class
   - Add bearing field
   - Add osm_way_id field
   - Update `get_neighbors()` to return edges with bearing

### Phase 3: API Endpoint (Pending)

**Pending Tasks:**
1. ❌ Create POST `/routes` endpoint in `src/server/app.py`
   - Request: `{points: [{lat, lon}], k: int, snap_k: int}`
   - Response: `{routes: [{route_id, distance_m, time_sec, geometry}]}`

2. ❌ Integrate snap_to_edge.py for point snapping
   - Use snap_k to find K nearest edges for each point
   - Try all combinations for best route

3. ❌ Integrate k_shortest_paths with turn penalties
   - Call `k_shortest_paths(graph, start, goal, k, use_turn_penalties=True)`
   - Return K alternatives

### Phase 4: Client Integration (Pending)

**Pending Tasks:**
1. ❌ Connect RoutePanel signals in `src/client/ui/widgets/main_window.py`
   - `self.sidebar.route_panel.get_routes_clicked.connect(self._on_get_k_routes)`
   - `self.sidebar.route_panel.route_selected.connect(self._on_route_selected)`

2. ❌ Implement handlers
   - `_on_get_k_routes(k)` - call API `/routes` endpoint
   - `_on_route_selected(route_id)` - highlight route on map

3. ❌ Add MapLibre layers for routes
   - `routes-inactive` (gray, width=3)
   - `routes-active` (green, width=5)
   - Update GeoJSON source on route change

### Phase 5: End-to-End Testing (Pending)

**Test Scenario:**
1. Load Arbat graph
2. Set start/end points on map
3. Click "Get Routes" with K=5
4. Verify 5 routes displayed in panel (sorted by time)
5. Click route #2 → map highlights it in green
6. Verify turn penalties apply (compare straight route vs sharp turn route)
7. Test Russian maxspeed: place route through Moscow residential (should use ru:urban=60 km/h)

---

## Technical Notes

**Why Split A* Implementation:**
- Original A* (state=node_id) is fast for simulation (thousands of agents)
- Turn-aware A* (state=(node,edge)) is slower but needed for K routes (user-facing)
- Split allows optimal performance for both use cases

**Why OSRM Profile:**
- User wants OSRM-style routing ("я бы взял весь этот конфиг с его таблицами")
- OSRM has 10+ years of real-world tuning
- Country-specific maxspeed tables critical for accuracy
- Speed tolerance (20%) matches OSRM behavior

**Why Turn Penalties:**
- U-turn on highway: +20s penalty or blocked
- Sharp turn (120°): +12s penalty
- Normal turn (60°): +7.5s penalty
- Straight (< 30°): 0s penalty
- Critical for realistic K routes (not just distance-optimal)

**Logging Architecture:**
- Using structlog for structured logs (as user requested: "логгирование мы вроде решили перебазывать в graphana")
- All modules log with context (profile_name, node_count, restriction_count)
- Ready for Grafana/Loki integration (not docker logs)

---

## Files Created/Modified

**New Files (5):**
1. `configs/car_profile.yaml` - Complete OSRM configuration
2. `src/data/osrm_profile.py` - Profile implementation
3. `src/data/osm_way_processor.py` - Way processing
4. `src/data/turn_restrictions.py` - Restriction manager
5. `tests/test_osrm_profile.py` - Profile tests

**Modified Files (2):**
1. `src/routing/pathfinding.py` - Added turn penalty support to A*
2. `requirements.txt` - Added PyYAML==6.0.1

**Test Status:**
- ✅ 12 profile tests passed
- ❌ Way processor tests (not created yet)
- ❌ Turn restrictions tests (not created yet)
- ❌ A* turn penalties tests (not created yet)

---

## Current Blocker: None

structlog was missing in venv - **RESOLVED** (installed 25.5.0)

**Ready to continue with Phase 2: Database Integration**
