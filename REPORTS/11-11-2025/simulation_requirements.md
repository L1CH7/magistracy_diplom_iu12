# Simulation System Requirements

## Overview
МАС система навигации для городского транспорта с динамической координацией 1000+ агентов.

---

## Core Concepts

### 1. Agent (Агент)
**Definition**: Автономная единица симуляции, представляющая транспортное средство.

**Properties**:
- `agent_id`: Уникальный идентификатор
- `current_position`: Текущее положение на графе (edge_id, progress [0.0-1.0])
- `assigned_route_id`: **Ссылка** на маршрут (НЕ снимок!)
- `driver_type`: Тип водителя ('normal', 'hurry')
- `sim_speed`: Множитель скорости симуляции (1.0 = real-time)
- `state`: Состояние ('moving', 'stopped', 'waiting', 'congestion')

**Behavior**:
- Следует назначенному маршруту динамически (по ссылке, не по снимку)
- При получении нового маршрута: проверяет, находится ли **на любом** ребре нового маршрута
- Проверяет направление движения (исключение: разворот должен быть явно в маршруте)
- Если на ребре нового маршрута + направление совпадает → сворачивает
- Если нет → продолжает старый маршрут до следующего пересечения
- **Важно**: Агент может проехать несколько ребер, пока новый маршрут строится и отдается

**Lifecycle**:
- Создание: Система координации назначает начальный маршрут
- Движение: Агент следует маршруту, обновляет позицию каждый кадр
- Rerouting: Получает новый маршрут от координатора (без удаления агента!)
- Завершение: Достигает конечной точки маршрута

---

### 2. Route (Маршрут)
**Definition**: Последовательность ребер графа от точки A до точки B.

**Properties**:
- `route_id`: Уникальный идентификатор
- `edge_ids`: Список edge_id в порядке следования
- `geometry`: Координаты для визуализации [(lon, lat), ...]
- `total_distance_m`: Общая длина маршрута
- `total_time_sec`: Предполагаемое время (без учета пробок)
- `start_point`: Начальная точка (lat, lon) + snap_radius
- `end_point`: Конечная точка (lat, lon) + snap_radius

**Snap Radius (радиус точности)**:
- Для точек пользователя: snap_radius > 0 (ищем ближайшее ребро в радиусе)
- Для позиции агента: snap_radius = 0 (агент **жестко** на ребре, никакого поиска)
- Параметр в API: `snap_radius` (number) или `snap_radii` (array для каждой точки)

**Types**:
- **Initial Route**: Построен от start_point до end_point
- **Reroute**: Построен от текущей позиции агента до end_point
  * start_point = current agent position
  * Учитывает предсказанные пробки

**Storage**:
- `route_cache`: In-memory хранилище маршрутов на сервере
- Ключ: можно использовать route_id или hash(edges)
- Маршруты могут обновляться динамически (не immutable!)

---

### 3. Graph (Дорожный граф)
**Definition**: Граф дорожной сети с ребрами (edges) и узлами (nodes).

**Edge Properties**:
- `edge_id`: Уникальный идентификатор
- `start_node_id`, `end_node_id`: Узлы
- `length_m`: Длина ребра (метры)
- `speed_limit_kmh`: Разрешенная скорость (из OSM)
- `lanes`: Количество полос
- `capacity`: Максимальное количество агентов (calculated: length_m / 5.0 * lanes)
- **`current_load`**: Текущее количество агентов на ребре (DYNAMIC!)
- **`effective_speed_kmh`**: Эффективная скорость с учетом загрузки (DYNAMIC!)
- `geometry`: LINESTRING координаты

**Dynamic Attributes**:
```python
# При превышении capacity:
if current_load > capacity:
    congestion_factor = current_load / capacity  # > 1.0
    effective_speed_kmh = speed_limit_kmh / (1 + 0.5 * (congestion_factor - 1))
else:
    effective_speed_kmh = speed_limit_kmh
```

---

## System Architecture

### Current Problems (Snapshot-based)

❌ **Agent stores route snapshot**:
```python
# BAD: Agent stores copy of route data
agent.route_edges = [101, 102, 103, ...]
agent.route_coords = [(37.123, 55.456), ...]
agent.edge_speed_limits = [60, 60, 40, ...]
```

**Issues**:
1. Agent cannot see route updates
2. Rerouting requires agent deletion and recreation
3. No support for dynamic congestion response

### Required Architecture (Route Reference)

✅ **Agent holds route_id reference**:
```python
# GOOD: Agent references route dynamically
agent.assigned_route_id = 42
agent.current_edge_index = 5  # Position on route

# Get current route dynamically:
route = route_cache.get(agent.assigned_route_id)
current_edge_id = route.edge_ids[agent.current_edge_index]
```

**Benefits**:
1. Rerouting without agent deletion
2. Route can be updated in cache
3. All agents on same route see updates
4. Supports dynamic coordination

---

## Dynamic Rerouting System

### Scenario: 1000 agents, congestion ahead

**Step 1: Congestion Detection**
```python
# Coordination module monitors edge load:
for edge_id, edge in graph.edges.items():
    if edge.current_load > edge.capacity * 0.8:
        # Congestion threshold: 80% of capacity
        forecast_congestion(edge_id, lookahead_seconds=20)
```

**Step 2: Predictive Analysis**
- Forecast congestion 20-60 seconds ahead
- Identify affected agents (those whose routes include congested edge)
- Calculate alternative routes avoiding congestion

**Step 3: Rerouting Decision**
```python
for agent in affected_agents:
    current_pos = agent.get_current_position()  # (edge_id, progress)
    
    # Build alternative route from current position
    new_route = find_alternative_route(
        start=current_pos,
        end=agent.destination,
        avoid_edges=[congested_edge_id],
        k=3  # Try 3 alternatives
    )
    
    # Assign new route (agent not deleted!)
    agent.assign_route(new_route.id)
```

**Step 4: Agent Route Following**
```python
def agent_update_position(agent, dt):
    # Get current route dynamically
    route = route_cache.get(agent.assigned_route_id)
    
    # Check if on correct edge
    expected_edge = route.edge_ids[agent.current_edge_index]
    actual_edge = agent.current_edge_id
    
    if actual_edge == expected_edge:
        # On route, continue
        agent.move_along_edge(dt)
    else:
        # Off route, check if on next edge of new route
        if actual_edge in route.edge_ids:
            # Find position in new route
            agent.current_edge_index = route.edge_ids.index(actual_edge)
            agent.move_along_edge(dt)
        else:
            # Completely off route, wait for new reroute
            agent.state = 'waiting'
```

---

## Edge Matching Logic

### Problem: Agent proехал поворот
Agent at edge 102, new route starts at edge 101 (behind agent).

**Solution**: Check if agent's current edge is **anywhere** in new route:

```python
def can_follow_new_route(agent, new_route):
    """Check if agent can follow new route from current position."""
    current_edge = agent.current_edge_id
    
    # Find current edge in new route
    if current_edge in new_route.edge_ids:
        # Agent is on new route, can follow it
        new_index = new_route.edge_ids.index(current_edge)
        agent.current_edge_index = new_index
        return True
    
    # Check if current edge connects to any edge in new route
    for i, route_edge in enumerate(new_route.edge_ids):
        if edges_connected(current_edge, route_edge):
            # Can switch at next intersection
            agent.pending_route_id = new_route.id
            agent.switch_at_edge = route_edge
            return True
    
    return False  # Completely off route
```

---

## Implementation Plan

### Phase 1: Refactor Agent to Route Reference
**Files**:
- `src/simulation/agent.py`: Remove snapshot fields, add `assigned_route_id`
- `src/server/app.py`: Agents query route_cache dynamically

**Changes**:
```python
# OLD
agent.route_edges = route_data['edges']
agent.route_coords = route_data['geometry']

# NEW
agent.assigned_route_id = route_id
# Agent queries route dynamically:
def get_current_position(agent, route_cache):
    route = route_cache[agent.assigned_route_id]
    edge = route.edge_ids[agent.current_edge_index]
    ...
```

### Phase 2: Mid-Route Rerouting API
**New Endpoint**: `POST /sim/agent/{id}/reroute`
```json
{
  "new_route_id": 43,
  "reason": "congestion_ahead"
}
```

**Behavior**:
- Agent checks current position vs new route
- If on new route → switch immediately
- If not → continue old route until intersection

### Phase 3: Congestion Simulation
**Track Edge Load**:
```python
# When agent enters edge:
graph.edges[edge_id].current_load += 1

# When agent leaves edge:
graph.edges[edge_id].current_load -= 1

# Update effective speed:
update_effective_speed(edge_id)
```

### Phase 4: Predictive Rerouting
**Coordination Module**:
- Monitor edge loads every 1 second
- Forecast congestion 20-60 seconds ahead
- Trigger rerouting for affected agents
- Limit reroutes: max 1 per agent per 30 seconds

---

## Known Issues (TODO)

### 1. OSM Incremental Tile Downloads
**Location**: `src/server/app.py` - `POST /osm/fetch_road_graph`

**Issue**: System returns cached bbox instead of downloading missing tiles.

**Required**:
- Calculate tile coverage for requested bbox
- Query database for existing tiles
- Identify missing tiles
- Download only missing tiles from Overpass API
- Merge with existing graph data
- Store new tiles in PostgreSQL

**Benefits**:
- Faster requests (reuse existing data)
- No duplicate downloads
- Expandable map coverage

### 2. Route Cache Memory Management
**Issue**: route_cache grows unbounded in memory.

**Required**:
- Implement LRU cache with size limit
- Store routes in database (PostgreSQL)
- Cache only active routes in memory
- Cleanup unused routes after 1 hour

### 3. Agent State Persistence
**Issue**: Agents lost on server restart (in-memory only).

**Required**:
- Store agent state in Redis or PostgreSQL
- Restore agents on server startup
- Support hot-reload without losing simulation state

---

## Testing Requirements

### Unit Tests
- Agent route reference logic
- Edge matching algorithm
- Congestion calculation
- Rerouting decision

### Integration Tests
- 10 agents on same route
- Congestion triggers rerouting
- Agent follows new route from mid-point

### Performance Tests
- 1000 agents simultaneous simulation
- Position update latency < 10ms per agent
- Rerouting decision < 100ms for 1000 agents

---

## Success Criteria

✅ **Basic Simulation** (Current):
- Single agent follows route with realistic speed
- Dynamic speed from OSM + RF rules
- Bearing rotation, ETA calculation

✅ **Dynamic Routing** (Required):
- Agent holds route_id reference (not snapshot)
- Rerouting without agent deletion
- Edge matching logic works

✅ **Congestion Simulation** (Required):
- 1000 agents tracked on graph
- Edge load affects effective_speed_kmh
- Predictive rerouting triggers before congestion

✅ **Coordination** (Future):
- Multi-agent route optimization
- Distributed decision making
- Real-time traffic prediction

---

**Document Created**: 2025-11-11  
**Author**: AI Assistant  
**Status**: Requirements Specification  
**Next Phase**: Architecture Refactoring
