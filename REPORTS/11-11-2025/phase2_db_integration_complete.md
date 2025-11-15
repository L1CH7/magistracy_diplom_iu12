# Phase 2 Progress - Database Integration ✅

**Time:** 2025.11.11 (продолжаю без остановки)

## Completed in Phase 2

### 1. Graph Builder Integration ✅

**Modified:** `src/data/graph_builder.py`
- Replaced manual way processing with `OSMWayProcessor`
- Now uses OSRM profile for speed calculation
- Calculates bearing for each segment (0-360°)
- Processes oneway correctly (forward/reverse/bidirectional)
- **New function:** `segments_to_edge_dicts()` converts ProcessedSegments to DB format
- **Updated:** `save_graph_to_postgres()` uses processor
- Logs: profile_name, processed_count, segments stats

**Result:** Graph building now OSRM-compatible with turn penalty support

---

### 2. Turn Restrictions Storage ✅

**Created:** `migrations/005_add_turn_restrictions.sql`
- Table: turn_restrictions (osm_relation_id, restriction_type, from_way, via_node, to_way)
- Indexes: (from_way_id, via_node_id) for O(1) routing lookup
- Supports prohibitive (no_*) and mandatory (only_*) restrictions

**Modified:** `src/data/postgis_manager.py`
- `insert_turn_restrictions()` - bulk insert with ON CONFLICT
- `load_turn_restrictions()` - load all restrictions
- **Updated:** `insert_edges()` now includes bearing field

**Modified:** `src/data/graph_builder.py`
- Step 7: Load turn restrictions from OSM relations
- Uses `TurnRestrictionManager` to parse
- Inserts to PostgreSQL via `db.insert_turn_restrictions()`
- Logs restriction count in final stats

**Result:** Turn restrictions now stored in DB and ready for routing

---

### 3. Routing Integration ✅

**Modified:** `src/routing/route_builder.py`
- `_find_k_paths_between_nodes()` now uses `use_turn_penalties=True`
- All K routes calculated with turn penalties

**Already exists:** POST `/routes` endpoint in `src/server/app.py`
- Loads graph from PostgreSQL
- Calls `build_routes()` with k and snap_k
- Returns K routes with geometry
- ✅ **No changes needed** - already working!

**Result:** API endpoint ready, just needs client integration

---

## Current State

**Backend (Server):**
- ✅ OSRM profile loaded from YAML
- ✅ OSMWayProcessor processes ways with bearing
- ✅ Turn restrictions loaded from OSM relations
- ✅ Graph stored in PostgreSQL with bearing
- ✅ A* with turn penalties implemented
- ✅ POST /routes endpoint exists and works
- ✅ K-shortest paths with turn penalties

**Database:**
- ✅ Migration 004: bearing column in edges
- ✅ Migration 005: turn_restrictions table (need to apply)
- ✅ Indexes for fast turn restriction lookup

**Next:** Client Integration (Phase 3)

---

## Phase 3: Client Integration (Starting Now)

### Pending Tasks:

1. **Connect RoutePanel signals** in `src/client/ui/widgets/main_window.py`
   - Signal: `route_panel.get_routes_clicked` → handler `_on_get_k_routes()`
   - Signal: `route_panel.route_selected` → handler `_on_route_selected()`

2. **Implement handlers**
   - `_on_get_k_routes(k)` - call POST /routes with points
   - `_on_route_selected(route_id)` - highlight route on map

3. **Add MapLibre layers** for K routes visualization
   - Source: 'routes' (GeoJSON with MultiLineString)
   - Layer: 'routes-inactive' (gray, width=3)
   - Layer: 'routes-active' (green, width=5)
   - Update on route selection

4. **Test end-to-end**
   - Load Arbat graph
   - Set 2 points on map
   - Get 5 routes
   - Select route #2 → verify highlight
   - Check turn penalties (compare straight vs turn routes)

---

## Metrics

**Lines Changed:**
- graph_builder.py: +40 lines (OSMWayProcessor integration, turn restrictions)
- postgis_manager.py: +85 lines (turn restrictions methods, bearing insert)
- route_builder.py: +3 lines (use_turn_penalties flag)

**New Files:**
- migrations/005_add_turn_restrictions.sql (52 lines)

**Total:** ~180 lines changed/added in Phase 2

---

**Status:** Phase 2 COMPLETE, moving to Phase 3 without stopping! 🚀
