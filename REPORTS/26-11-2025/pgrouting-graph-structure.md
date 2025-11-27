# 🗂️ pgRouting Graph Structure: Полная Спецификация

**Дата:** 27 ноября 2025  
**Статус:** Детальное руководство структуры графа  
**Цель:** Точная схема БД для работы с pgRouting с учетом speed, capacity, restrictions

---

## 📌 Обзор

pgRouting требует **жесткую структуру** для своих функций:
- `pgr_dijkstra()` требует: `id, source, target, cost, reverse_cost`
- `pgr_KSP()` требует: `id, source, target, cost, reverse_cost`
- Все остальное — наше расширение для модели

**Наша структура = pgRouting base + наши поля (speed, capacity, access, barriers)**

---

## 🔑 Жесткие Требования pgRouting

### Таблица edges ДОЛЖНА иметь

```
id              SERIAL PRIMARY KEY           -- pgRouting требует! (уникальный ID каждого edge)
source          BIGINT                       -- pgRouting требует! (начальный node)
target          BIGINT                       -- pgRouting требует! (конечный node)
cost            FLOAT / NUMERIC              -- pgRouting требует! (cost в одном направлении)
reverse_cost    FLOAT / NUMERIC              -- pgRouting требует! (cost в обратном направлении)
                                             -- -1 = нет обратного направления (oneway)
```

**Это минимум для pgRouting!**

---

## 📊 Полная Схема Графа (Наша Расширенная)

### graphs.nodes

```sql
CREATE TABLE graphs.nodes (
    id BIGSERIAL PRIMARY KEY,
    
    -- OSM связь
    osm_node_id BIGINT,
    
    -- Геометрия
    geom GEOMETRY(Point, 4326) NOT NULL,
    
    -- Тип ноды
    type VARCHAR(50) DEFAULT 'intersection',
    -- Values: 'intersection', 'uturn', 'barrier', 'traffic_signal', 'endpoint'
    
    -- Барьер на ноде?
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),          -- gate, boom, bollard, block, wall
    barrier_penalty_sec INT DEFAULT 0,
    
    -- Служебные
    is_intersection BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_graphs_nodes_geom ON graphs.nodes USING GIST(geom);
CREATE INDEX idx_graphs_nodes_osm_id ON graphs.nodes(osm_node_id);
CREATE INDEX idx_graphs_nodes_type ON graphs.nodes(type);
```

### graphs.edges ⭐ (ГЛАВНАЯ)

```sql
CREATE TABLE graphs.edges (
    -- ========== PGEROUTING BASE (ЖЕСТКИЕ ТРЕБОВАНИЯ) ==========
    id SERIAL PRIMARY KEY,                              -- pgRouting требует
    source BIGINT REFERENCES graphs.nodes(id),          -- pgRouting требует
    target BIGINT REFERENCES graphs.nodes(id),          -- pgRouting требует
    cost FLOAT NOT NULL,                                -- pgRouting требует (cost forward)
    reverse_cost FLOAT NOT NULL,                        -- pgRouting требует (cost backward, -1 = нет)
    
    -- ========== ГЕОМЕТРИЯ ==========
    geom GEOMETRY(LineString, 4326) NOT NULL,
    length_m FLOAT NOT NULL,                           -- ← TRIGGER вычисляет!
    bearing_start FLOAT,                               -- направление в начале
    bearing_end FLOAT,                                 -- направление в конце
    
    -- ========== OSM ИСТОЧНИК ==========
    osm_way_id BIGINT,
    osm_tags JSONB,                                    -- raw OSM tags (для debug)
    
    -- ========== ДОРОГА АТРИБУТЫ ==========
    highway VARCHAR(50) NOT NULL,
    -- Values: motorway, motorway_link, trunk, primary, secondary, 
    --         residential, living_street, service, unclassified, etc.
    
    name VARCHAR(255),
    lanes INT DEFAULT 1,
    oneway BOOLEAN DEFAULT false,
    
    -- ========== СКОРОСТЬ (с дефолтами!) ==========
    maxspeed_kmh INT NOT NULL,
    -- Приоритет: OSM maxspeed tag > config override > default_speeds[highway]
    -- Examples: 120 (motorway), 90 (primary), 60 (residential), 20 (service)
    
    -- ========== CAPACITY (для congestion model) ==========
    base_capacity INT NOT NULL,
    -- max vehicles per hour that can traverse at free-flow speed
    -- Примеры:
    --   motorway 2lanes: 3800 vehicles/hour
    --   primary 2lanes: 1600 vehicles/hour
    --   residential: 800 vehicles/hour
    
    current_load INT DEFAULT 0,
    -- текущее количество агентов на этом edge
    -- обновляется в реальном времени (или раз в 1 сек)
    
    -- ========== ДОСТУП & ОГРАНИЧЕНИЯ ==========
    access_type VARCHAR(50) DEFAULT 'public',
    -- Values: 'public', 'destination', 'private', 'no'
    -- Используется в маршрутизации для разных типов агентов
    
    motor_vehicle VARCHAR(50),
    -- Values: 'yes', 'no', 'destination', 'private'
    -- Явный запрет на проезд для моторных средств
    
    is_restricted BOOLEAN DEFAULT false,
    -- True если нужно пересчитать маршрут (через rerouting)
    
    barrier_penalty_sec INT DEFAULT 0,
    -- штраф за ворота/барьеры на этом edge
    -- примеры: 30 (regular), 15 (taxi), 5 (emergency)
    
    service VARCHAR(50),
    -- Values: 'driveway', 'parking', 'alley', 'parking_aisle', etc.
    -- Указывает на то что это парковка или подъезд
    
    -- ========== DYNAMIC FIELDS (GENERATED ALWAYS STORED) ==========
    effective_speed_kmh FLOAT GENERATED ALWAYS AS (
        -- Эффективная скорость с учетом congestion
        CASE
            WHEN current_load = 0 THEN maxspeed_kmh
            WHEN current_load <= base_capacity THEN maxspeed_kmh
            ELSE GREATEST(5.0, maxspeed_kmh * (2.0 - current_load::FLOAT / base_capacity))
        END
    ) STORED,
    
    cost FLOAT GENERATED ALWAYS AS (
        -- ГЛАВНЫЙ: используется в pgr_dijkstra, pgr_KSP
        -- cost в секундах (время преодоления edge)
        length_m / (effective_speed_kmh / 3.6)
        -- Formula: time = distance / speed
        -- length_m / (speed_kmh * 1000 / 3600) = length_m / (speed_kmh / 3.6)
    ) STORED,
    
    reverse_cost FLOAT GENERATED ALWAYS AS (
        -- ЖЕСТКОЕ ТРЕБОВАНИЕ pgRouting
        -- -1 означает что обратного направления нет (oneway)
        CASE WHEN oneway THEN -1.0 ELSE cost END
    ) STORED,
    
    -- ========== СЛУЖЕБНЫЕ ==========
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== TRIGGER: Автоматическое вычисление length_m ==========
CREATE OR REPLACE FUNCTION compute_edge_length()
RETURNS TRIGGER AS $$
BEGIN
    -- ST_Length в метрах через Web Mercator для точности
    NEW.length_m := ST_Length(ST_Transform(NEW.geom, 3857));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_length_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION compute_edge_length();

-- ========== ИНДЕКСЫ ==========
CREATE INDEX idx_graphs_edges_source ON graphs.edges(source);
CREATE INDEX idx_graphs_edges_target ON graphs.edges(target);
CREATE INDEX idx_graphs_edges_source_target ON graphs.edges(source, target);
CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geom);
CREATE INDEX idx_graphs_edges_access ON graphs.edges(access_type);
CREATE INDEX idx_graphs_edges_current_load ON graphs.edges(current_load);
CREATE INDEX idx_graphs_edges_highway ON graphs.edges(highway);
```

---

## 🛑 Turn Restrictions (Отдельная таблица)

### graphs.turn_restrictions

```sql
CREATE TABLE graphs.turn_restrictions (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    
    -- Тип ограничения
    restriction_type VARCHAR(50) NOT NULL,
    -- Values: 'no_left_turn', 'no_right_turn', 'no_straight_on', 'no_u_turn',
    --         'only_left_turn', 'only_right_turn', 'only_straight_on', 'only_u_turn'
    
    -- Как это представлено в OSM relation:
    --   from_way: дорога ДО перекрестка (в направлении движения)
    --   via_node: перекресток (ноду между from_way и to_way)
    --   to_way: дорога ПОСЛЕ перекрестка
    
    from_edge_id INT REFERENCES graphs.edges(id),
    via_node_id BIGINT REFERENCES graphs.nodes(id),
    to_edge_id INT REFERENCES graphs.edges(id),
    
    -- Когда это ограничение действует?
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    days_of_week VARCHAR(50),  -- например: 'Mon-Fri', 'weekends', 'all'
    hours VARCHAR(50),         -- например: '08:00-09:00', 'all'
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_turn_restrictions_from ON graphs.turn_restrictions(from_edge_id);
CREATE INDEX idx_turn_restrictions_via ON graphs.turn_restrictions(via_node_id);
CREATE INDEX idx_turn_restrictions_to ON graphs.turn_restrictions(to_edge_id);
CREATE INDEX idx_turn_restrictions_type ON graphs.turn_restrictions(restriction_type);
```

**Как использовать в pgRouting:**

```sql
-- Расширить граф с ограничениями через условия маршрутизации
-- Это нужно делать ПЕРЕД вызовом pgr_dijkstra:

-- Способ 1: Фильтровать edges где ограничение действует
SELECT * FROM graphs.edges
WHERE NOT EXISTS (
    SELECT 1 FROM graphs.turn_restrictions tr
    WHERE tr.from_edge_id = edges.id
    AND tr.restriction_type = 'no_left_turn'  -- или другое
    AND NOW() BETWEEN tr.valid_from AND tr.valid_to
);

-- Способ 2: Использовать WITH для усложненного query
WITH allowed_edges AS (
    SELECT edges.*
    FROM graphs.edges
    WHERE ... условие на ограничения ...
)
SELECT * FROM pgr_dijkstra('SELECT ... FROM allowed_edges', $1, $2, ...)
```

---

## ⚡ Congestion Model (Capacity + current_load)

### Как работает:

```sql
-- Каждый edge имеет:
-- base_capacity: INT (max vehicles/hour при свободном потоке)
-- current_load: INT (текущее количество агентов, real-time)

-- GENERATED ALWAYS вычисляет:
-- effective_speed_kmh = f(current_load / base_capacity)

-- BPR Congestion Function:
effective_speed_kmh = CASE
    WHEN current_load = 0 THEN maxspeed_kmh
    WHEN current_load <= base_capacity THEN maxspeed_kmh
    ELSE GREATEST(5.0, maxspeed_kmh * (2.0 - current_load::FLOAT / base_capacity))
END;

-- Примеры:
-- current_load = 0 → speed = maxspeed (100 км/ч)
-- current_load = base_capacity (1600) → speed = maxspeed (100 км/ч)
-- current_load = 2 * base_capacity (3200) → speed = GREATEST(5.0, 100 * (2 - 3200/1600))
--                                              = GREATEST(5.0, 100 * 0) = 5 км/ч (пробка!)
-- current_load = 1.5 * base_capacity → speed = GREATEST(5.0, 100 * (2 - 1.5)) = 50 км/ч
```

### Обновление current_load:

```python
# src/server/services/coordination/congestion_tracker.py

class CongestionTracker:
    """Отслеживать и обновлять загруженность рёбер."""
    
    def __init__(self, db_pool, edges_dict):
        self.db_pool = db_pool
        self.edges = edges_dict
    
    async def update_edge_loads(self, agents_state: Dict[str, AgentState]):
        """
        Обновить current_load для всех edges на основе текущих позиций агентов.
        
        Вызывается раз в 1 сек (или реже для Performance).
        """
        # Подсчитать агентов на каждом edge
        edge_counts = {}
        
        for agent_id, agent_state in agents_state.items():
            if not agent_state.is_running:
                continue
            
            edge_id = agent_state.current_edge_id
            edge_counts[edge_id] = edge_counts.get(edge_id, 0) + 1
        
        # Batch update в БД
        async with self.db_pool.acquire() as conn:
            # Reset все (те что не обновим = 0)
            await conn.execute("UPDATE graphs.edges SET current_load = 0")
            
            # Обновить те что есть
            for edge_id, count in edge_counts.items():
                await conn.execute(
                    "UPDATE graphs.edges SET current_load = $1 WHERE id = $2",
                    count, edge_id
                )
```

---

## 🚀 GraphBuilder: Как Строить Граф из OSM

### Шаги:

```python
# src/server/services/graph_builder/graph_builder.py

class GraphBuilder:
    """Построить pgRouting граф из raw OSM."""
    
    async def build_graph(self, bbox: Tuple[float, float, float, float]):
        """
        1. Найти все перекрёстки (nodes)
        2. Разбить ways на segments по перекрёсткам
        3. Создать edges с правильными cost/reverse_cost
        4. Добавить barriers & turn restrictions
        5. Установить capacity на основе highway type
        """
        
        logger.info("Step 1: Find intersections")
        intersections = await self._find_intersections(bbox)
        # Ищем node с usage >= 2 (несколько ways используют этот node)
        
        logger.info("Step 2: Create nodes")
        await self._create_nodes_from_intersections(intersections)
        
        logger.info("Step 3: Split ways into segments")
        await self._split_ways_into_edges(intersections, bbox)
        
        logger.info("Step 4: Set speeds (maxspeed_kmh)")
        await self._set_speeds_with_defaults(bbox)
        
        logger.info("Step 5: Set capacity based on highway type")
        await self._set_capacity_by_highway_type()
        
        logger.info("Step 6: Add barriers")
        await self._add_barriers_from_osm(bbox)
        
        logger.info("Step 7: Add turn restrictions")
        await self._add_turn_restrictions_from_osm(bbox)
        
        logger.info("Graph build complete!")
    
    async def _set_speeds_with_defaults(self, bbox):
        """
        Установить maxspeed_kmh с приоритетом:
        1. OSM maxspeed tag (если есть)
        2. Config override
        3. Default speeds по highway type
        """
        
        config_overrides = {
            # city: 60, residential: 50, etc.
        }
        
        default_speeds = {
            'motorway': 120,
            'motorway_link': 80,
            'trunk': 100,
            'primary': 90,
            'secondary': 80,
            'residential': 60,
            'living_street': 20,
            'service': 20,
            # ... остальное
        }
        
        async with self.graph_db_pool.acquire() as conn:
            # Update edges где есть OSM maxspeed tag
            await conn.execute("""
                UPDATE graphs.edges SET maxspeed_kmh = (osm_tags->>'maxspeed')::INT
                WHERE osm_tags ? 'maxspeed' AND (osm_tags->>'maxspeed') ~ '^[0-9]+$'
            """)
            
            # Update edges где есть config override
            for highway_type, speed in config_overrides.items():
                await conn.execute(
                    "UPDATE graphs.edges SET maxspeed_kmh = $1 WHERE highway = $2 AND maxspeed_kmh IS NULL",
                    speed, highway_type
                )
            
            # Update с default speeds
            for highway_type, speed in default_speeds.items():
                await conn.execute(
                    "UPDATE graphs.edges SET maxspeed_kmh = $1 WHERE highway = $2 AND maxspeed_kmh IS NULL",
                    speed, highway_type
                )
    
    async def _set_capacity_by_highway_type(self):
        """
        Установить base_capacity на основе highway type и lanes.
        
        Capacity = vehicles per hour at free-flow speed.
        
        Примерные значения:
          motorway 2lanes: 3800 vehicles/hour
          primary 2lanes: 1600 vehicles/hour
          residential: 800 vehicles/hour
        """
        
        capacity_lookup = {
            # (highway_type, lanes) -> capacity
            ('motorway', 1): 2000,
            ('motorway', 2): 3800,
            ('motorway', 3): 5700,
            ('trunk', 1): 1200,
            ('trunk', 2): 2400,
            ('primary', 1): 800,
            ('primary', 2): 1600,
            ('secondary', 1): 600,
            ('secondary', 2): 1200,
            ('residential', None): 800,
            ('service', None): 300,
            ('living_street', None): 300,
        }
        
        async with self.graph_db_pool.acquire() as conn:
            for (highway, lanes), capacity in capacity_lookup.items():
                if lanes is None:
                    await conn.execute(
                        "UPDATE graphs.edges SET base_capacity = $1 WHERE highway = $2",
                        capacity, highway
                    )
                else:
                    await conn.execute(
                        "UPDATE graphs.edges SET base_capacity = $1 WHERE highway = $2 AND lanes = $3",
                        capacity, highway, lanes
                    )
    
    async def _add_barriers_from_osm(self, bbox):
        """
        Найти barriers из osm.barriers и добавить penalty к edges.
        """
        async with self.graph_db_pool.acquire() as conn:
            # Для каждого barrier: найти ближайший edge
            barriers = await conn.fetch("""
                SELECT id, geom, barrier_type, access
                FROM osm.barriers
                WHERE geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)
            """, bbox[0], bbox[1], bbox[2], bbox[3])
            
            for barrier in barriers:
                # Найти ближайший edge
                closest_edge = await conn.fetchrow("""
                    SELECT id, barrier_penalty_sec
                    FROM graphs.edges
                    ORDER BY ST_Distance(geom, $1)
                    LIMIT 1
                """, barrier['geom'])
                
                if closest_edge:
                    # Добавить penalty
                    penalty = 30 if barrier['access'] == 'private' else 10
                    await conn.execute(
                        "UPDATE graphs.edges SET barrier_penalty_sec = barrier_penalty_sec + $1 WHERE id = $2",
                        penalty, closest_edge['id']
                    )
```

---

## 🎯 Пример: Как pgRouting будет использовать граф

```python
# Вызов pgr_dijkstra (Dijkstra algorithm)
query = """
    SELECT * FROM pgr_dijkstra(
        'SELECT id, source, target, cost, reverse_cost FROM graphs.edges',
        $1,  -- start_node
        $2,  -- end_node
        directed := true
    )
"""

# pgRouting внутри:
# 1. Читает edges: id, source, target, cost, reverse_cost
# 2. cost = length_m / (effective_speed_kmh / 3.6)  [GENERATED ALWAYS вычисляет это]
# 3. effective_speed_kmh = f(current_load / base_capacity)  [зависит от congestion]
# 4. reverse_cost = -1.0 если oneway, иначе = cost
# 5. Запускает Dijkstra с этими costs
# 6. Возвращает кратчайший путь в секундах
```

---

## 📝 Итоговая Структура (Чеклист)

### ✅ Что ОБЯЗАТЕЛЬНО нужно в edges:

- `id` — pgRouting требует
- `source` — pgRouting требует
- `target` — pgRouting требует
- `cost` — pgRouting требует (GENERATED ALWAYS!)
- `reverse_cost` — pgRouting требует (GENERATED ALWAYS!)
- `geom` — для ST_Length в TRIGGER
- `length_m` — вычисляется TRIGGER'ом
- `maxspeed_kmh` — для cost вычисления
- `current_load` — для congestion модели
- `base_capacity` — для congestion модели
- `oneway` — для reverse_cost

### ✅ Что нужно для ACCESS CONTROL:

- `access_type` — public/private/destination/no
- `motor_vehicle` — явный запрет
- `service` — указывает на парковку/подъезд
- `barrier_penalty_sec` — штраф за ворота

### ✅ Что нужно для DYNAMIC REROUTING:

- `current_load` — обновляется в реальном времени
- `effective_speed_kmh` — вычисляется автоматически
- `cost` — зависит от effective_speed_kmh

### ✅ Что нужно для TURN RESTRICTIONS:

- Отдельная таблица `graphs.turn_restrictions`
- Ссылаются на edges через (from_edge, via_node, to_edge)

---

## 🔗 Связь с pgRouting Query:

```sql
-- Это query который мы передаем в pgr_dijkstra:
SELECT 
    id,                    -- pgRouting требует
    source,                -- pgRouting требует
    target,                -- pgRouting требует
    cost,                  -- pgRouting требует (length / speed)
    reverse_cost           -- pgRouting требует (-1 если oneway)
FROM graphs.edges

-- Дополнительные поля НЕ используются pgRouting напрямую
-- но используются ДО вызова (для фильтрации, исключения и т.д.):
WHERE 
    access_type IN ('public', 'destination')  -- ← Наше ограничение
    AND motor_vehicle != 'no'                 -- ← Наше ограничение
    AND current_load < base_capacity * 2      -- ← Опциональный фильтр congestion
```

---

## 📚 Резюме

**pgRouting жестко требует:**
- id, source, target, cost, reverse_cost

**Наша архитектура добавляет:**
- length_m, maxspeed_kmh, current_load, base_capacity → вычисляют cost
- access_type, motor_vehicle, barrier_penalty_sec → контроль доступа
- turn_restrictions (отдельная таблица) → запреты поворотов

**Граф автоматически:**
- Пересчитывает cost когда меняется current_load (GENERATED ALWAYS!)
- Обновляет effective_speed_kmh на основе congestion

**Это всё уже было в финальном гайде!** ✅

Но теперь это в отдельном документе с полной спецификацией SQL и примерами.
