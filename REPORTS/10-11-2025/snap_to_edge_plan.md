# Snap to Edge + Turn Penalties: Implementation Plan

**Date**: 2025-11-10  
**Status**: In Progress  
**Goal**: Реализовать корректный snap к рёбрам с учётом поворотов и oneway

## Проблема

**Текущая реализация** (snap to node):
```
User click (55.751, 37.618)
         ↓
   Find nearest NODE
         ↓
   Node может быть далеко от клика!
```

**Проблемы**:
- ❌ Точка привязывается к началу/концу ребра, а не к ближайшей точке на ребре
- ❌ Нет учёта разворотов (oneway)
- ❌ Нет штрафов за повороты
- ❌ Неточная геометрия маршрута

## Решение: Snap to Edge

```
User click (55.751, 37.618)
         ↓
   PostGIS ST_ClosestPoint(edge, point)
         ↓
   Exact position ON edge (fraction 0.0-1.0)
         ↓
   Virtual node at position
         ↓
   A* with turn penalties
```

## Architecture

### 1. Edge Snap Result

```python
@dataclass
class EdgeSnap:
    edge_id: int
    start_node_id: int
    end_node_id: int
    fraction: float          # 0.0-1.0 на ребре
    position_m: float        # Абсолютная позиция в метрах
    distance_to_edge_m: float  # Расстояние от точки до ребра
    bearing: float           # Азимут ребра (для turn costs)
    geometry: List[(lon, lat)]  # Геометрия ребра
```

### 2. PostGIS Query

```sql
WITH point AS (
    SELECT ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom
)
SELECT 
    e.id,
    e.start_node_id,
    e.end_node_id,
    e.length_m,
    -- Позиция на ребре (0.0-1.0)
    ST_LineLocatePoint(e.geometry, point.geom) AS fraction,
    -- Расстояние до ребра
    ST_Distance(e.geometry::geography, point.geom::geography) AS distance_m,
    -- Азимут ребра
    degrees(ST_Azimuth(
        ST_StartPoint(e.geometry),
        ST_EndPoint(e.geometry)
    )) AS bearing,
    ST_AsText(e.geometry) AS geometry_wkt
FROM edges e, point
WHERE ST_DWithin(
    e.geometry::geography,
    point.geom::geography,
    100.0  -- max 100m
)
ORDER BY e.geometry <-> point.geom
LIMIT 5
```

### 3. Virtual Nodes for Start/End

```python
def create_virtual_node(snap: EdgeSnap, graph: Graph):
    """
    Создаёт виртуальный узел на ребре.
    
    Если snap.fraction = 0.0 → используем start_node_id
    Если snap.fraction = 1.0 → используем end_node_id
    Иначе → создаём временный узел с новым ID
    """
    if snap.fraction < 0.01:
        return snap.start_node_id, []
    elif snap.fraction > 0.99:
        return snap.end_node_id, []
    else:
        # Создаём виртуальный узел
        v_node_id = -(snap.edge_id * 2)  # Negative ID для временных узлов
        
        # Разбиваем ребро на 2 части:
        # 1. start_node → v_node (fraction 0.0 → snap.fraction)
        # 2. v_node → end_node (fraction snap.fraction → 1.0)
        
        edge = graph.get_edge(snap.edge_id)
        
        virtual_edges = [
            VirtualEdge(
                id=-(snap.edge_id * 2 + 1),
                start_node_id=edge.start_node_id,
                end_node_id=v_node_id,
                length_m=edge.length_m * snap.fraction,
                # ... копируем остальные атрибуты
            ),
            VirtualEdge(
                id=-(snap.edge_id * 2 + 2),
                start_node_id=v_node_id,
                end_node_id=edge.end_node_id,
                length_m=edge.length_m * (1.0 - snap.fraction),
                # ...
            )
        ]
        
        return v_node_id, virtual_edges
```

### 4. A* with Turn Penalties

```python
def astar_with_turns(
    graph: Graph,
    start_node_id: int,
    goal_node_id: int,
    virtual_edges: Dict[int, VirtualEdge] = None
):
    """
    A* с учётом поворотов.
    
    State: (node_id, prev_edge_id)
    Cost: edge.travel_time + turn_penalty(prev_edge, curr_edge)
    """
    
    # Priority queue: (f_score, node_id, prev_edge_id, g_score)
    open_set = []
    heapq.heappush(open_set, (0.0, start_node_id, None, 0.0))
    
    # came_from: (node_id, prev_edge_id) → (parent_node, parent_edge, used_edge)
    came_from = {}
    
    # g_score: (node_id, prev_edge_id) → cost
    g_score = {(start_node_id, None): 0.0}
    
    while open_set:
        f, current_node, prev_edge_id, current_g = heapq.heappop(open_set)
        
        if current_node == goal_node_id:
            # Reconstruct path
            return reconstruct_path(came_from, current_node, prev_edge_id)
        
        # Get neighbors (учитываем virtual edges)
        neighbors = graph.get_neighbors(current_node)
        if virtual_edges and current_node in virtual_edges:
            neighbors.extend(virtual_edges[current_node])
        
        for edge in neighbors:
            neighbor_id = edge.end_node_id
            
            # Calculate turn penalty
            turn_penalty = 0.0
            if prev_edge_id is not None:
                prev_edge = graph.get_edge(prev_edge_id)
                if prev_edge:
                    turn_penalty = get_turn_penalty(
                        prev_edge.bearing,
                        edge.bearing,
                        edge.oneway
                    )
            
            # Total cost
            tentative_g = current_g + edge.get_travel_time() + turn_penalty
            
            state = (neighbor_id, edge.id)
            if state not in g_score or tentative_g < g_score[state]:
                g_score[state] = tentative_g
                f_score = tentative_g + heuristic(neighbor_id, goal_node_id)
                
                heapq.heappush(open_set, (f_score, neighbor_id, edge.id, tentative_g))
                came_from[state] = (current_node, prev_edge_id, edge.id)
    
    return None  # No path found
```

### 5. Turn Penalty Function

```python
def get_turn_penalty(
    prev_bearing: float,  # 0-360°
    curr_bearing: float,  # 0-360°
    is_oneway: bool
) -> float:
    """
    Штраф за поворот в секундах.
    
    Turn types:
    - Straight (0-30°): 0s
    - Turn (30-90°): 5s
    - Sharp turn (90-150°): 15s
    - U-turn (150-180°): 30s (inf if oneway)
    """
    angle_diff = abs(calculate_turn_angle(prev_bearing, curr_bearing))
    
    if angle_diff < 30:
        return 0.0
    elif angle_diff < 90:
        return 5.0
    elif angle_diff < 150:
        return 15.0
    else:
        # U-turn
        if is_oneway:
            return float('inf')  # Impossible on oneway
        return 30.0


def calculate_turn_angle(bearing1: float, bearing2: float) -> float:
    """
    Угол поворота между двумя азимутами.
    
    Returns: -180..180 (positive = right, negative = left)
    """
    diff = bearing2 - bearing1
    
    while diff > 180:
        diff -= 360
    while diff < -180:
        diff += 360
    
    return diff
```

### 6. Route Geometry with Interpolation

```python
def build_route_geometry_with_snaps(
    graph: Graph,
    route_edges: List[int],
    start_snap: EdgeSnap,
    goal_snap: EdgeSnap
) -> List[Tuple[float, float]]:
    """
    Строит геометрию маршрута с учётом snap точек.
    """
    coords = []
    
    # First edge: от start_snap.fraction до конца ребра
    first_edge = graph.get_edge(route_edges[0])
    segment = interpolate_edge_segment(
        first_edge.geometry,
        start_snap.fraction,
        1.0
    )
    coords.extend(segment)
    
    # Middle edges: полностью
    for edge_id in route_edges[1:-1]:
        edge = graph.get_edge(edge_id)
        coords.extend(edge.geometry[1:])  # Skip first (duplicate)
    
    # Last edge: от начала до goal_snap.fraction
    last_edge = graph.get_edge(route_edges[-1])
    segment = interpolate_edge_segment(
        last_edge.geometry,
        0.0,
        goal_snap.fraction
    )
    coords.extend(segment[1:])  # Skip first (duplicate)
    
    return coords
```

## Implementation Steps

### Step 1: Add bearing to edges table ✅

```sql
-- Migration 004: Add bearing column
ALTER TABLE edges 
ADD COLUMN bearing FLOAT GENERATED ALWAYS AS (
    degrees(ST_Azimuth(
        ST_StartPoint(geometry),
        ST_EndPoint(geometry)
    ))
) STORED;

CREATE INDEX idx_edges_bearing ON edges(bearing);
```

### Step 2: Implement snap_to_edge.py ✅

- [x] EdgeSnap dataclass
- [x] snap_point_to_edges() with PostGIS query
- [x] interpolate_edge_segment()
- [x] calculate_turn_angle()
- [x] get_turn_penalty()

### Step 3: Update pathfinding.py

- [ ] Modify A* to accept virtual edges
- [ ] Add turn penalty to cost function
- [ ] Update state to (node_id, prev_edge_id)

### Step 4: Update route_builder.py

- [ ] Use snap_to_edges() instead of snap_to_nodes()
- [ ] Create virtual nodes for start/end points
- [ ] Pass virtual edges to A*
- [ ] Build geometry with interpolation

### Step 5: Update server API

- [ ] POST /routes endpoint uses new snap logic
- [ ] Return EdgeSnap info in response

### Step 6: Update client UI

- [ ] Add "Get Routes" button
- [ ] Add K slider/input
- [ ] Display routes on map (green selected, gray others)
- [ ] Click route to select

## Testing Plan

### Test 1: Point on edge middle

```python
# Point посреди ребра (fraction ~0.5)
point = (55.751, 37.618)
snap = snap_point_to_edges(db, 55.751, 37.618, k=1)[0]
assert 0.4 < snap.fraction < 0.6
assert snap.distance_to_edge_m < 50.0
```

### Test 2: Turn penalty calculation

```python
# Straight
assert get_turn_penalty(0, 10, False) == 0.0

# Right turn
assert get_turn_penalty(0, 80, False) == 5.0

# Sharp turn
assert get_turn_penalty(0, 120, False) == 15.0

# U-turn on bidirectional
assert get_turn_penalty(0, 180, False) == 30.0

# U-turn on oneway
assert get_turn_penalty(0, 180, True) == float('inf')
```

### Test 3: Route with turns

```python
# Route with multiple turns
points = [
    (55.751, 37.618),  # Start
    (55.752, 37.620),  # Via (requires turn)
    (55.753, 37.619),  # End (requires another turn)
]

routes = build_routes_with_snaps(graph, points, k=3)

# Best route should avoid sharp turns if possible
assert routes[0].total_time_sec < routes[1].total_time_sec
```

## Performance Considerations

### Snap Performance

- **PostGIS KNN** (`<->` operator): ~1-2ms per point
- **ST_DWithin** (100m radius): filters most edges
- **Total snap time**: ~5-10ms for 2 points

### A* with Turn Penalties

- **Overhead**: +10-20% compared to basic A*
- **Reason**: Larger state space (node_id, prev_edge_id)
- **Mitigation**: Good heuristic + early termination

### Virtual Edges

- **Memory**: +2 edges per snap point (start/end)
- **Lookup**: O(1) in dict
- **Total overhead**: negligible

## UI Integration

### Client: Add "Get Routes" Button

```python
# src/client/ui/widgets/route_panel.py
class RoutePanel(QWidget):
    def __init__(self):
        self.k_spinbox = QSpinBox()
        self.k_spinbox.setRange(1, 10)
        self.k_spinbox.setValue(5)
        
        self.get_routes_btn = QPushButton("Get Routes")
        self.get_routes_btn.clicked.connect(self.on_get_routes)
        
        self.routes_list = QListWidget()
        self.routes_list.itemClicked.connect(self.on_route_selected)
    
    def on_get_routes(self):
        points = self.map_widget.get_clicked_points()
        k = self.k_spinbox.value()
        
        # Call API
        response = api_client.post_routes(points, k)
        
        # Display routes
        self.display_routes(response['routes'])
        
        # Draw on map
        self.map_widget.draw_routes(response['routes'])
```

### Server: Response Format

```json
{
  "routes": [
    {
      "id": 0,
      "edges": [1234, 5678, 9012],
      "total_distance_m": 1234.5,
      "total_time_sec": 98.7,
      "geometry": [[37.618, 55.751], [37.619, 55.752], ...],
      "snaps": {
        "start": {
          "edge_id": 1234,
          "fraction": 0.35,
          "distance_to_edge_m": 12.3
        },
        "end": {
          "edge_id": 9012,
          "fraction": 0.78,
          "distance_to_edge_m": 8.9
        }
      }
    }
  ],
  "selected": 0
}
```

## Future Enhancements

### Phase 2.2: Turn Restrictions from OSM

```sql
-- OSM turn restrictions
CREATE TABLE turn_restrictions (
    id SERIAL PRIMARY KEY,
    from_way_id BIGINT,
    via_node_id BIGINT,
    to_way_id BIGINT,
    restriction_type VARCHAR(50)  -- no_left_turn, no_right_turn, etc.
);

-- В A*: проверяем (prev_edge, via_node, curr_edge) не в запретах
```

### Phase 2.3: Bidirectional Search

```python
def bidirectional_astar(graph, start, goal):
    # Forward search from start
    # Backward search from goal
    # Meet in the middle → 2x speedup
```

### Phase 3: Integration with Agent Simulation

```python
@dataclass
class Agent:
    id: int
    route_edges: List[int]
    current_edge_idx: int
    position_m: float  # Position on current edge
    velocity_ms: float
    snap_info: EdgeSnap  # Original start snap
```

## Comparison with OSRM

| Feature | OSRM | Our Solution |
|---------|------|--------------|
| Preprocessing | Hours (CH) | Seconds (load graph) |
| Query Time | 1-5ms | 50-100ms |
| Dynamic Weights | ❌ (needs rebuild) | ✅ Real-time |
| Turn Costs | ✅ | ✅ |
| Turn Restrictions | ✅ | ⏳ Phase 2.2 |
| Snap to Edge | ✅ | ✅ |
| U-turns | ✅ | ✅ |
| Traffic Integration | ❌ | ✅ (BPR function) |

**Вывод**: Для динамического графа с изменяющимися весами наше решение лучше OSRM!

## Summary

✅ **Snap to edge** - точная привязка к рёбрам  
✅ **Turn penalties** - учёт поворотов  
✅ **Oneway handling** - невозможность разворотов на oneway  
✅ **Virtual nodes** - корректная геометрия  
⏳ **Turn restrictions** - Phase 2.2  
⏳ **Bidirectional search** - Phase 2.3  

**Статус**: Ready to implement Steps 3-6
