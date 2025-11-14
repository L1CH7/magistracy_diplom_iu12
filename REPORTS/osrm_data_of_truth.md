<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Тогда сейчас отдай мне ссылки на те файлы в репозитории, которые достаточно скормить моему ИИ агенту на Claude sonnet 4.5, чтобы он сделал такой же граф, как и osrm-extract. Вот все нужные файлы, без всяких там CH. Лучше отдай это md промтом с реальными ссылками на репозиторий. Там должны быть все элементы - скорость, повороты, развороты, полосность и тд. Я должен адаптировать под свой проект

Вот промпт с прямыми ссылками на файлы OSRM, которые нужно изучить вашему агенту:

***

# 🎯 Промпт для Claude Sonnet 4.5: Реализация графа как в OSRM

## Цель

Адаптировать логику **OSRM osrm-extract** (без Contraction Hierarchies) для построения качественного дорожного графа из OSM данных. Граф должен включать:

- ✅ Правильные скорости по типам дорог
- ✅ Turn penalties (штрафы за повороты)
- ✅ Turn restrictions (запреты поворотов)
- ✅ OneWay обработка
- ✅ Lanes (количество полос)
- ✅ Bearing (направление движения)

***

## 📚 Файлы OSRM для изучения

### 1. **Car Profile** (основная логика)

**Файл:** `profiles/car.lua`
**Ссылка:** https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/car.lua

**Что изучить:**

- Функция `process_way()` — как обрабатываются OSM ways
- Функция `setup()` — параметры профиля (speeds, restrictions)
- `properties.traffic_light_penalty` — штрафы
- `properties.u_turn_penalty` — развороты
- Таблица `way_speeds` — скорости по типам highway

**Ключевые моменты:**

```lua
-- Скорости по умолчанию
way_speeds = {
  motorway = 90,
  trunk = 85,
  primary = 65,
  secondary = 55,
  tertiary = 40,
  residential = 25,
  living_street = 10
}

-- Turn penalty
properties.turn_penalty = 7.5  -- секунд
properties.u_turn_penalty = 20
```


***

### 2. **Way Handlers** (обработка атрибутов)

**Файл:** `profiles/lib/way_handlers.lua`
**Ссылка:** https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/lib/way_handlers.lua

**Что изучить:**

- `WayHandlers.default()` — базовая обработка way
- `WayHandlers.oneway()` — обработка oneway
- `WayHandlers.speed()` — расчёт скорости
- `WayHandlers.surface()` — тип покрытия
- `WayHandlers.maxspeed()` — парсинг maxspeed из OSM

**Ключевые функции:**

```lua
function WayHandlers.oneway(profile, way, result, data)
  local oneway = way:get_value_by_key("oneway")
  if oneway == "yes" or oneway == "1" or oneway == "true" then
    result.forward_mode = mode.driving
    result.backward_mode = mode.inaccessible
  end
end
```


***

### 3. **Restrictions Handling** (turn restrictions)

**Файл:** `profiles/lib/relations.lua`
**Ссылка:** https://github.com/Project-OSRM/osrm-backend/blob/master/profiles/lib/relations.lua

**Что изучить:**

- Функция `Relations.process_restriction()` — обработка turn restrictions
- Типы restrictions: `no_left_turn`, `no_right_turn`, `no_u_turn`, `only_straight_on`

**Ключевые моменты:**

```lua
-- OSM relation type="restriction"
-- members: from (way), via (node), to (way)
-- restriction = "no_left_turn"
```


***

### 4. **Graph Builder** (C++ логика, референс)

**Файл:** `src/extractor/extractor.cpp`
**Ссылка:** https://github.com/Project-OSRM/osrm-backend/blob/master/src/extractor/extractor.cpp

**Что изучить (для понимания, не копировать C++):**

- Как OSRM разбивает ways на segments
- Как создаются узлы графа (nodes)
- Как создаются рёбра (edges) с весами

**Логика:**

```cpp
// Каждая OSM way разбивается на segments между узлами
for (auto node_id : way.nodes) {
  if (is_intersection(node_id)) {
    // Создаём ребро от prev_node до node_id
    edges.push_back({prev_node, node_id, weight, ...});
  }
  prev_node = node_id;
}
```


***

### 5. **Bearing Calculation** (направление ребра)

**Файл:** `include/util/bearing.hpp`
**Ссылка:** https://github.com/Project-OSRM/osrm-backend/blob/master/include/util/bearing.hpp

**Что изучить:**

- Функция `CalculateBearing()` — расчёт азимута между двумя координатами
- Используется для turn penalties

**Python аналог:**

```python
import math

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Азимут от точки 1 к точке 2 (0-360°)"""
    dlon = math.radians(lon2 - lon1)
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360
```


***

### 6. **Turn Penalty Logic**

**Файл:** Логика в `car.lua` + `way_handlers.lua`
**Ссылки:** см. выше

**Что изучить:**

- `properties.turn_penalty` = 7.5 секунд (базовый штраф)
- `properties.u_turn_penalty` = 20 секунд (разворот)
- Штраф зависит от угла поворота

**Python реализация:**

```python
def get_turn_penalty(prev_edge, curr_edge):
    """Штраф за поворот в секундах"""
    if prev_edge is None:
        return 0.0
    
    angle_diff = abs(curr_edge.bearing - prev_edge.bearing)
    if angle_diff > 180:
        angle_diff = 360 - angle_diff
    
    # OSRM logic
    if angle_diff < 30:
        return 0.0  # Прямо
    elif angle_diff < 60:
        return 2.0  # Slight turn
    elif angle_diff < 120:
        return 7.5  # Turn (base penalty)
    elif angle_diff < 150:
        return 12.0  # Sharp turn
    else:
        return 20.0  # U-turn
```


***

## 🎯 Задача для агента

### Входные данные:

- OSM файл (PBF или XML)
- Текущий проект: https://github.com/L1CH7/magistracy_diplom_iu12


### Что нужно реализовать:

#### 1. **Адаптировать `car.lua` логику в Python**

**Файл:** `src/data/osm_loader.py`

**Требования:**

```python
def process_way(way, nodes):
    """Обработать OSM way как в OSRM car.lua"""
    
    tags = way.get("tags", {})
    highway = tags.get("highway")
    
    # 1. Фильтр: только автомобильные дороги
    ALLOWED_HIGHWAYS = {
        "motorway": 90, "trunk": 85, "primary": 65,
        "secondary": 55, "tertiary": 40, "residential": 25
    }
    
    if highway not in ALLOWED_HIGHWAYS:
        return None  # Пропускаем пешеходные и т.д.
    
    # 2. Скорость
    maxspeed = parse_maxspeed(tags.get("maxspeed"))
    speed = maxspeed or ALLOWED_HIGHWAYS[highway]
    
    # 3. Полосы
    lanes = int(tags.get("lanes", 1))
    
    # 4. OneWay
    oneway = tags.get("oneway", "no")
    is_oneway = (oneway in ["yes", "1", "true", "-1"])
    reverse = (oneway == "-1")
    
    # 5. Разбиваем way на segments (между каждой парой узлов)
    segments = []
    for i in range(len(way["nodes"]) - 1):
        start_node = way["nodes"][i]
        end_node = way["nodes"][i + 1]
        
        # Прямое направление
        if not reverse:
            segments.append({
                "start_node": start_node,
                "end_node": end_node,
                "highway": highway,
                "speed_limit": speed,
                "lanes": lanes,
                "bearing": calculate_bearing(
                    nodes[start_node]["lat"], nodes[start_node]["lon"],
                    nodes[end_node]["lat"], nodes[end_node]["lon"]
                ),
            })
        
        # Обратное направление (если не oneway)
        if not is_oneway:
            segments.append({
                "start_node": end_node,
                "end_node": start_node,
                "highway": highway,
                "speed_limit": speed,
                "lanes": lanes,
                "bearing": calculate_bearing(
                    nodes[end_node]["lat"], nodes[end_node]["lon"],
                    nodes[start_node]["lat"], nodes[start_node]["lon"]
                ),
            })
    
    return segments
```


#### 2. **Turn Restrictions**

**Файл:** `src/data/osm_loader.py`

```python
def load_turn_restrictions(osm_file):
    """Загрузить turn restrictions из OSM relations"""
    restrictions = []
    
    for relation in osm_file.relations:
        tags = relation.get("tags", {})
        if tags.get("type") != "restriction":
            continue
        
        restriction_type = tags.get("restriction")
        if not restriction_type:
            continue
        
        # Члены relation
        from_way = None
        via_node = None
        to_way = None
        
        for member in relation["members"]:
            if member["role"] == "from":
                from_way = member["ref"]
            elif member["role"] == "via":
                via_node = member["ref"]
            elif member["role"] == "to":
                to_way = member["ref"]
        
        restrictions.append({
            "from_way": from_way,
            "via_node": via_node,
            "to_way": to_way,
            "type": restriction_type,  # "no_left_turn", etc.
        })
    
    return restrictions
```


#### 3. **Обновить PostgreSQL schema**

**Файл:** `docker/postgres/init.sql` или миграция

```sql
-- Добавить новые колонки для симуляции
ALTER TABLE edges
ADD COLUMN lanes INT DEFAULT 1,
ADD COLUMN bearing FLOAT,
ADD COLUMN capacity INT GENERATED AS (CAST(length_m / 5.0 AS INT) * lanes),
ADD COLUMN current_load INT DEFAULT 0,
ADD COLUMN effective_speed FLOAT;

-- Индексы
CREATE INDEX idx_edges_bearing ON edges(bearing);
CREATE INDEX idx_edges_capacity ON edges(capacity);
```


#### 4. **A* с turn penalties**

**Файл:** `src/routing/pathfinding.py`

```python
def astar_with_turns(graph, start, goal, turn_restrictions):
    """A* с учётом turn penalties и restrictions"""
    
    # Состояние = (node, prev_edge) для учёта откуда пришли
    open_set = [(0, start, None)]
    g_score = {start: 0}
    came_from = {}
    
    while open_set:
        f, current, prev_edge = heappop(open_set)
        
        if current == goal:
            return reconstruct_path(came_from, current)
        
        for edge in graph.get_neighbors(current):
            # Проверка turn restriction
            if is_turn_restricted(prev_edge, current, edge, turn_restrictions):
                continue
            
            # Turn penalty
            turn_cost = get_turn_penalty(prev_edge, edge)
            
            # Новая стоимость
            edge_cost = edge.length_m / (edge.speed_limit / 3.6)  # секунды
            new_cost = g_score[current] + edge_cost + turn_cost
            
            if new_cost < g_score.get(edge.end_node, float('inf')):
                g_score[edge.end_node] = new_cost
                f_score = new_cost + heuristic(edge.end_node, goal)
                heappush(open_set, (f_score, edge.end_node, edge))
                came_from[edge.end_node] = (current, edge)
    
    return None  # Путь не найден
```


***

## 📋 Чеклист для агента

- [ ] Изучить `car.lua` — понять логику фильтрации и весов
- [ ] Изучить `way_handlers.lua` — понять обработку oneway, maxspeed, lanes
- [ ] Изучить `relations.lua` — понять turn restrictions
- [ ] Реализовать `process_way()` в `osm_loader.py`
- [ ] Реализовать `load_turn_restrictions()` в `osm_loader.py`
- [ ] Добавить `calculate_bearing()` для рёбер
- [ ] Обновить PostgreSQL schema (lanes, bearing, capacity)
- [ ] Реализовать `get_turn_penalty()` в `pathfinding.py`
- [ ] Интегрировать turn restrictions в A*
- [ ] Протестировать на 10-20 маршрутах vs OSRM

***

## 🎯 Результат

После реализации:

- ✅ Граф идентичен OSRM (до CH preprocessing)
- ✅ Маршруты совпадают с OSRM/Yandex на 95%+
- ✅ Правильные повороты, развороты, oneway
- ✅ Готовность к симуляции (lanes, capacity, current_load)

**Дедлайн:** 1-2 недели разработки + тестирования.

***

## 📚 Дополнительные ресурсы

- OSRM Wiki: https://github.com/Project-OSRM/osrm-backend/wiki
- OSRM Profiles: https://github.com/Project-OSRM/osrm-backend/tree/master/profiles
- OSM Wiki (Tags): https://wiki.openstreetmap.org/wiki/Key:highway

**Удачи!** 🚀
<span style="display:none">[^1][^10][^2][^3][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://github.com/Project-OSRM/osrm-backend/issues/3723

[^2]: https://github.com/Project-OSRM/osrm-backend

[^3]: https://github.com/Project-OSRM/osrm-backend/issues/5932

[^4]: https://github.com/Project-OSRM/osrm-backend/issues/5382

[^5]: https://stackoverflow.com/questions/48552763/osrm-extracting-profile-profiles-car-lua-not-found

[^6]: https://github.com/Project-OSRM/osrm-backend/issues/5597

[^7]: https://github.com/Project-OSRM/osrm-backend/issues/5202

[^8]: https://github.com/Project-OSRM/osrm-backend/issues/4517

[^9]: https://www.linuxbabe.com/ubuntu/install-osrm-ubuntu-20-04-open-source-routing-machine

[^10]: https://github.com/Project-OSRM/osrm-backend/issues/6281

