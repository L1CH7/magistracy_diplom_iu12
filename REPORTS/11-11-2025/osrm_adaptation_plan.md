# 🎯 План адаптации OSRM Extract для нашего графа

## Дата: 11.11.2025
## Статус: Планирование

---

## 1. Цель

Адаптировать логику построения графа из **OSRM osrm-extract** (БЕЗ Contraction Hierarchies) для максимальной реалистичности маршрутов.

**Ключевое отличие от OSRM:**
- ❌ НЕ используем CH preprocessing (нужна динамика)
- ✅ Используем PostGIS + Python + A* с turn penalties
- ✅ Сохраняем всю логику извлечения данных из OSM

---

## 2. Что берём из OSRM

### 2.1. Car Profile (`profiles/car.lua`)

**Скорости по типам дорог:**
```lua
speeds = {
  motorway        = 90,
  motorway_link   = 45,
  trunk           = 85,
  trunk_link      = 40,
  primary         = 65,
  primary_link    = 30,
  secondary       = 55,
  secondary_link  = 25,
  tertiary        = 40,
  tertiary_link   = 20,
  unclassified    = 25,
  residential     = 25,
  living_street   = 10,
  service         = 15
}
```

**Turn penalties:**
```lua
turn_penalty = 7.5  -- секунд (базовый поворот)
u_turn_penalty = 20  -- секунд (разворот)
```

**Фильтрация дорог:**
```lua
avoid = {
  'area', 'reversible', 'impassable', 
  'hov_lanes', 'steps', 'construction', 'proposed'
}
```

### 2.2. Way Handlers (`profiles/lib/way_handlers.lua`)

**Обработка oneway:**
- `oneway=yes|1|true` → только forward
- `oneway=-1` → только backward
- `oneway=no` → оба направления

**Обработка maxspeed:**
- Парсинг `maxspeed` тега из OSM
- Приоритет: maxspeed > profile speed

**Обработка lanes:**
- `lanes=N` → количество полос
- Default: 1 полоса

### 2.3. Turn Restrictions (`profiles/lib/relations.lua`)

**OSM relation type="restriction":**
```
members:
  - from: way_id (откуда едем)
  - via: node_id (через какой узел)
  - to: way_id (куда едем)
restriction:
  - no_left_turn
  - no_right_turn
  - no_u_turn
  - no_straight_on
  - only_left_turn
  - only_right_turn
  - only_straight_on
```

### 2.4. Bearing Calculation

**Из `include/util/bearing.hpp`:**
```python
def calculate_bearing(lat1, lon1, lat2, lon2):
    """Азимут от точки 1 к точке 2 (0-360°)"""
    dlon = math.radians(lon2 - lon1)
    lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
    
    x = math.sin(dlon) * math.cos(lat2_rad)
    y = (math.cos(lat1_rad) * math.sin(lat2_rad) - 
         math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon))
    
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360
```

---

## 3. Архитектура адаптации

### 3.1. Текущее состояние (что уже есть)

```
✅ PostGIS база данных
✅ nodes таблица (id, osm_node_id, lat, lon)
✅ edges таблица (id, osm_way_id, start_node_id, end_node_id, length_m, speed_limit_kmh, 
                  lanes, oneway, highway_type, capacity, base_travel_time_sec, 
                  bearing, current_load, effective_speed_kmh)
✅ Graph класс с adjacency list
✅ A* pathfinding (базовый, без turn penalties)
✅ snap_to_edge.py (PostGIS snapping)
```

### 3.2. Что нужно добавить

#### 📁 `src/data/osrm_profile.py` (НОВЫЙ)
**Назначение:** Конфигурация OSRM car profile в Python

```python
"""OSRM Car Profile Configuration"""

class CarProfile:
    """Car routing profile based on OSRM car.lua"""
    
    # Скорости по типам дорог (км/ч)
    HIGHWAY_SPEEDS = {
        'motorway': 90,
        'motorway_link': 45,
        'trunk': 85,
        'trunk_link': 40,
        'primary': 65,
        'primary_link': 30,
        'secondary': 55,
        'secondary_link': 25,
        'tertiary': 40,
        'tertiary_link': 20,
        'unclassified': 25,
        'residential': 25,
        'living_street': 10,
        'service': 15,
    }
    
    # Turn penalties (секунды)
    TURN_PENALTY = 7.5
    U_TURN_PENALTY = 20.0
    TRAFFIC_LIGHT_PENALTY = 2.0
    
    # Фильтр дорог
    ALLOWED_HIGHWAYS = set(HIGHWAY_SPEEDS.keys())
    
    AVOID_HIGHWAY_TAGS = {
        'area', 'proposed', 'construction', 
        'abandoned', 'platform', 'raceway'
    }
    
    # Penalties для типов сервисных дорог
    SERVICE_PENALTIES = {
        'alley': 0.5,
        'parking': 0.5,
        'parking_aisle': 0.5,
        'driveway': 0.5,
        'drive-through': 0.5,
    }
    
    @staticmethod
    def get_speed(highway_type: str, maxspeed: Optional[int] = None) -> float:
        """Получить скорость для типа дороги"""
        default_speed = CarProfile.HIGHWAY_SPEEDS.get(highway_type, 25)
        if maxspeed:
            return min(maxspeed, default_speed * 1.2)  # allow 20% over profile
        return default_speed
    
    @staticmethod
    def get_turn_penalty(angle_diff: float, is_oneway: bool = False) -> float:
        """Получить штраф за поворот (OSRM логика)"""
        if angle_diff < 30:
            return 0.0  # Straight
        elif angle_diff < 60:
            return 2.0  # Slight turn
        elif angle_diff < 120:
            return CarProfile.TURN_PENALTY  # Normal turn
        elif angle_diff < 150:
            return 12.0  # Sharp turn
        else:
            penalty = CarProfile.U_TURN_PENALTY
            if is_oneway:
                penalty = float('inf')  # U-turn impossible on oneway
            return penalty
```

#### 📁 `src/data/osm_way_processor.py` (НОВЫЙ)
**Назначение:** Обработка OSM ways как в OSRM

```python
"""OSM Way Processing (OSRM-style)"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from src.data.osrm_profile import CarProfile

@dataclass
class ProcessedSegment:
    """Обработанный сегмент дороги (направленный)"""
    start_node_id: int
    end_node_id: int
    highway_type: str
    speed_limit_kmh: float
    lanes: int
    oneway: bool
    bearing: float
    length_m: float
    osm_way_id: int
    
class OSMWayProcessor:
    """Обработчик OSM ways по логике OSRM"""
    
    def __init__(self, profile: CarProfile = None):
        self.profile = profile or CarProfile()
    
    def process_way(
        self, 
        way: Dict, 
        nodes: Dict[int, Dict]
    ) -> List[ProcessedSegment]:
        """Обработать OSM way → список направленных сегментов
        
        Args:
            way: OSM way с тегами
            nodes: Dict[node_id] → {lat, lon}
            
        Returns:
            Список ProcessedSegment (может быть 0, если дорога не подходит)
        """
        tags = way.get('tags', {})
        highway = tags.get('highway')
        
        # 1. Фильтр: только разрешённые типы дорог
        if highway not in self.profile.ALLOWED_HIGHWAYS:
            return []
        
        # 2. Проверка на avoid tags
        if any(tag in tags for tag in self.profile.AVOID_HIGHWAY_TAGS):
            return []
        
        # 3. Парсинг атрибутов
        maxspeed = self._parse_maxspeed(tags.get('maxspeed'))
        speed = self.profile.get_speed(highway, maxspeed)
        
        lanes = int(tags.get('lanes', 1))
        
        oneway_tag = tags.get('oneway', 'no')
        is_oneway, is_reverse = self._parse_oneway(oneway_tag, highway)
        
        # 4. Разбиваем way на сегменты (между каждой парой узлов)
        segments = []
        way_nodes = way['nodes']
        
        for i in range(len(way_nodes) - 1):
            start_id = way_nodes[i]
            end_id = way_nodes[i + 1]
            
            if start_id not in nodes or end_id not in nodes:
                continue  # Skip if node not loaded
            
            start_node = nodes[start_id]
            end_node = nodes[end_id]
            
            # Calculate bearing
            bearing_forward = calculate_bearing(
                start_node['lat'], start_node['lon'],
                end_node['lat'], end_node['lon']
            )
            
            # Calculate length
            length = haversine_distance(
                start_node['lat'], start_node['lon'],
                end_node['lat'], end_node['lon']
            )
            
            # Forward direction (если не reverse oneway)
            if not is_reverse:
                segments.append(ProcessedSegment(
                    start_node_id=start_id,
                    end_node_id=end_id,
                    highway_type=highway,
                    speed_limit_kmh=speed,
                    lanes=lanes,
                    oneway=is_oneway,
                    bearing=bearing_forward,
                    length_m=length,
                    osm_way_id=way['id']
                ))
            
            # Backward direction (если НЕ oneway)
            if not is_oneway:
                bearing_backward = (bearing_forward + 180) % 360
                segments.append(ProcessedSegment(
                    start_node_id=end_id,
                    end_node_id=start_id,
                    highway_type=highway,
                    speed_limit_kmh=speed,
                    lanes=lanes,
                    oneway=False,
                    bearing=bearing_backward,
                    length_m=length,
                    osm_way_id=way['id']
                ))
        
        return segments
    
    def _parse_maxspeed(self, maxspeed: Optional[str]) -> Optional[int]:
        """Парсинг maxspeed тега"""
        if not maxspeed:
            return None
        
        # Remove units
        maxspeed = maxspeed.replace('mph', '').replace('kmh', '').strip()
        
        try:
            speed = int(maxspeed)
            # Convert mph to kmh if needed
            if 'mph' in maxspeed:
                speed = int(speed * 1.60934)
            return speed
        except:
            return None
    
    def _parse_oneway(
        self, 
        oneway_tag: str, 
        highway: str
    ) -> Tuple[bool, bool]:
        """Парсинг oneway тега
        
        Returns:
            (is_oneway, is_reverse)
        """
        # Некоторые типы дорог oneway по умолчанию
        if highway in {'motorway', 'motorway_link'}:
            if oneway_tag == 'no':
                return (False, False)
            return (True, False)
        
        if oneway_tag in {'yes', '1', 'true'}:
            return (True, False)
        
        if oneway_tag == '-1':
            return (True, True)  # Reverse oneway
        
        return (False, False)
```

#### 📁 `src/data/turn_restrictions.py` (НОВЫЙ)
**Назначение:** Загрузка и обработка turn restrictions

```python
"""Turn Restrictions from OSM Relations"""

from typing import Dict, List, Set, Tuple
from dataclasses import dataclass

@dataclass
class TurnRestriction:
    """Turn restriction из OSM relation"""
    from_way_id: int
    via_node_id: int
    to_way_id: int
    restriction_type: str  # no_left_turn, only_straight_on, etc.
    
    def is_prohibited(self) -> bool:
        """Проверка, это запрет или разрешение"""
        return self.restriction_type.startswith('no_')
    
    def is_only(self) -> bool:
        """Проверка, это 'only' restriction"""
        return self.restriction_type.startswith('only_')

class TurnRestrictionsManager:
    """Менеджер turn restrictions"""
    
    def __init__(self):
        self.restrictions: List[TurnRestriction] = []
        # Индекс: (from_way, via_node) → [restrictions]
        self._index: Dict[Tuple[int, int], List[TurnRestriction]] = {}
    
    def load_from_osm(self, osm_relations: List[Dict]):
        """Загрузить restrictions из OSM relations"""
        for relation in osm_relations:
            tags = relation.get('tags', {})
            
            if tags.get('type') != 'restriction':
                continue
            
            restriction_type = tags.get('restriction')
            if not restriction_type:
                continue
            
            # Парсинг members
            from_way = None
            via_node = None
            to_way = None
            
            for member in relation.get('members', []):
                role = member.get('role')
                ref = member.get('ref')
                
                if role == 'from' and member.get('type') == 'way':
                    from_way = ref
                elif role == 'via' and member.get('type') == 'node':
                    via_node = ref
                elif role == 'to' and member.get('type') == 'way':
                    to_way = ref
            
            if from_way and via_node and to_way:
                restriction = TurnRestriction(
                    from_way_id=from_way,
                    via_node_id=via_node,
                    to_way_id=to_way,
                    restriction_type=restriction_type
                )
                self.restrictions.append(restriction)
                
                # Индексируем
                key = (from_way, via_node)
                if key not in self._index:
                    self._index[key] = []
                self._index[key].append(restriction)
    
    def is_turn_allowed(
        self, 
        from_edge_osm_way_id: int,
        via_node_id: int,
        to_edge_osm_way_id: int
    ) -> bool:
        """Проверить, разрешён ли поворот"""
        key = (from_edge_osm_way_id, via_node_id)
        restrictions = self._index.get(key, [])
        
        if not restrictions:
            return True  # No restrictions
        
        # Проверяем prohibitions
        for r in restrictions:
            if r.is_prohibited() and r.to_way_id == to_edge_osm_way_id:
                return False  # Explicit prohibition
        
        # Проверяем only restrictions
        only_restrictions = [r for r in restrictions if r.is_only()]
        if only_restrictions:
            # Если есть only, то разрешён только to_way из only
            allowed = any(r.to_way_id == to_edge_osm_way_id 
                         for r in only_restrictions)
            return allowed
        
        return True  # No restrictions blocking this turn
```

#### 📁 Update `src/routing/pathfinding.py`
**Добавить turn penalties в A***

```python
def astar_with_turns(
    graph: Graph,
    start_node_id: int,
    goal_node_id: int,
    restrictions: TurnRestrictionsManager
) -> Optional[List[int]]:
    """A* с учётом turn penalties и restrictions
    
    State: (node_id, prev_edge_id) для учёта направления
    """
    from heapq import heappush, heappop
    
    # Начальное состояние: (node, None)
    open_set = [(0, start_node_id, None)]
    g_score = {(start_node_id, None): 0}
    came_from = {}
    
    while open_set:
        f, current_node, prev_edge_id = heappop(open_set)
        
        if current_node == goal_node_id:
            return _reconstruct_path(came_from, (current_node, prev_edge_id))
        
        # Получаем исходящие рёбра
        for edge_id in graph.adjacency_list.get(current_node, []):
            edge = graph.edges[edge_id]
            
            # Проверка turn restriction
            if prev_edge_id is not None:
                prev_edge = graph.edges[prev_edge_id]
                if not restrictions.is_turn_allowed(
                    prev_edge.osm_way_id,
                    current_node,
                    edge.osm_way_id
                ):
                    continue  # Turn restricted
            
            # Turn penalty
            turn_cost = 0.0
            if prev_edge_id is not None:
                prev_edge = graph.edges[prev_edge_id]
                angle_diff = abs(edge.bearing - prev_edge.bearing)
                if angle_diff > 180:
                    angle_diff = 360 - angle_diff
                turn_cost = CarProfile.get_turn_penalty(angle_diff, edge.oneway)
            
            # Edge cost (время в секундах)
            edge_cost = edge.get_travel_time()
            
            # Новая стоимость
            new_g = g_score[(current_node, prev_edge_id)] + edge_cost + turn_cost
            
            next_state = (edge.end_node_id, edge_id)
            
            if new_g < g_score.get(next_state, float('inf')):
                g_score[next_state] = new_g
                h = _heuristic(graph, edge.end_node_id, goal_node_id)
                f_score = new_g + h
                heappush(open_set, (f_score, edge.end_node_id, edge_id))
                came_from[next_state] = (current_node, prev_edge_id)
    
    return None  # No path found
```

---

## 4. План реализации (Step-by-Step)

### Phase 1: Профиль и обработка ways (1-2 дня)
- [ ] Создать `osrm_profile.py` с CarProfile
- [ ] Создать `osm_way_processor.py` с OSMWayProcessor
- [ ] Обновить `osm_loader.py` для использования OSMWayProcessor
- [ ] Тестирование: сравнить скорости/oneway с текущими

### Phase 2: Turn restrictions (2-3 дня)
- [ ] Создать `turn_restrictions.py` с TurnRestrictionsManager
- [ ] Обновить `osm_loader.py` для загрузки relations
- [ ] Сохранить restrictions в PostgreSQL (новая таблица)
- [ ] Тестирование: найти примеры turn restrictions в Арбате

### Phase 3: A* с turn penalties (1-2 дня)
- [ ] Обновить `pathfinding.py` с `astar_with_turns()`
- [ ] Интеграция TurnRestrictionsManager
- [ ] Тестирование: сравнить маршруты с/без turn penalties

### Phase 4: Интеграция и тестирование (2-3 дня)
- [ ] Обновить API `/routes` для использования нового A*
- [ ] Тестирование на 20+ маршрутах
- [ ] Сравнение с OSRM/Yandex Maps
- [ ] Документирование отличий

**Итого:** 6-10 дней разработки

---

## 5. PostgreSQL Schema Updates

### 5.1. Новая таблица turn_restrictions

```sql
CREATE TABLE IF NOT EXISTS turn_restrictions (
    id SERIAL PRIMARY KEY,
    from_way_osm_id BIGINT NOT NULL,
    via_node_osm_id BIGINT NOT NULL,
    to_way_osm_id BIGINT NOT NULL,
    restriction_type VARCHAR(50) NOT NULL,
    -- no_left_turn, no_right_turn, only_straight_on, etc.
    
    CONSTRAINT unique_restriction 
        UNIQUE (from_way_osm_id, via_node_osm_id, to_way_osm_id)
);

CREATE INDEX idx_turn_restrictions_lookup 
    ON turn_restrictions(from_way_osm_id, via_node_osm_id);
```

### 5.2. Обновление edges таблицы

```sql
-- Уже есть, но проверим:
ALTER TABLE edges 
    ADD COLUMN IF NOT EXISTS osm_way_id BIGINT;

-- Индекс для быстрого поиска по osm_way_id
CREATE INDEX IF NOT EXISTS idx_edges_osm_way 
    ON edges(osm_way_id);
```

---

## 6. Тестирование

### 6.1. Unit Tests

```python
# tests/test_osrm_profile.py
def test_highway_speeds():
    assert CarProfile.get_speed('motorway') == 90
    assert CarProfile.get_speed('residential') == 25
    assert CarProfile.get_speed('motorway', maxspeed=110) == 90  # capped

def test_turn_penalties():
    assert CarProfile.get_turn_penalty(0) == 0.0  # straight
    assert CarProfile.get_turn_penalty(45) == 2.0  # slight
    assert CarProfile.get_turn_penalty(90) == 7.5  # turn
    assert CarProfile.get_turn_penalty(170) == 20.0  # u-turn
    assert CarProfile.get_turn_penalty(170, oneway=True) == float('inf')
```

### 6.2. Integration Tests

```python
# tests/test_osm_way_processor.py
def test_oneway_processing():
    way = {
        'id': 123,
        'tags': {'highway': 'primary', 'oneway': 'yes'},
        'nodes': [1, 2, 3]
    }
    nodes = {...}
    segments = processor.process_way(way, nodes)
    
    # Должно быть 2 сегмента (1→2, 2→3), все forward
    assert len(segments) == 2
    assert all(s.oneway for s in segments)
```

### 6.3. Comparison with OSRM

**Тестовые маршруты:**
1. Арбат: пл. Арбатские Ворота → Смоленская площадь
2. С поворотом: Красная площадь → ВДНХ
3. С разворотом: Тверская → обратно по односторонней
4. С turn restriction: найти примеры в OSM

**Метрики:**
- Длина маршрута (метры)
- Время маршрута (секунды)
- Количество поворотов
- Соответствие OSRM/Yandex (>90%)

---

## 7. Expected Results

После реализации:

✅ **Граф идентичен OSRM** (до CH preprocessing)
✅ **Маршруты реалистичны** (учитываются повороты, развороты)
✅ **Turn restrictions работают** (no_left_turn и т.д.)
✅ **Динамические веса** (в отличие от OSRM)
✅ **Готовность к симуляции** (lanes, capacity, current_load)

**Performance:**
- Построение графа: 10-30 секунд (без CH)
- A* query: 50-200ms (зависит от расстояния)
- Turn restrictions check: O(1) благодаря индексу

---

## 8. References

- OSRM car.lua: https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua
- OSRM way_handlers: https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/lib/way_handlers.lua
- OSRM relations: https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/lib/relations.lua
- OSM Turn Restrictions: https://wiki.openstreetmap.org/wiki/Relation:restriction

---

## 9. Notes

**Важные отличия от OSRM:**

1. **Препроцессинг:**
   - OSRM: Contraction Hierarchies (часы)
   - Мы: Загрузка в PostgreSQL (секунды)

2. **Динамика:**
   - OSRM: Статические веса
   - Мы: Динамические веса (BPR, current_load)

3. **Query time:**
   - OSRM: 1-5ms (благодаря CH)
   - Мы: 50-200ms (A* на полном графе)

**Это нормально!** Наша цель — симуляция с динамикой, не production-роутинг для миллионов запросов.

---

**Автор:** AI Agent  
**Версия:** 1.0  
**Следующий шаг:** Реализация Phase 1 (osrm_profile.py + osm_way_processor.py)
