# 🔧 ПЕРЕДЕЛКА: Правильная Организация Миграций и Граф БД

**Дата:** 28 ноября 2025  
**Статус:** КРИТИЧЕСКИЙ РЕФАКТОРИНГ  
**Проблема:** Текущие миграции организованы неправильно, граф не оптимален

---

## 🔴 Проблемы в Текущих Миграциях

### 1. **GENERATED ALWAYS вычисляется на каждый SELECT** ❌

```sql
-- Плохо (текущее):
length_m DOUBLE PRECISION GENERATED ALWAYS AS (
    ST_Length(ST_Transform(geometry, 3857))
) STORED,
```

**Почему плохо:**
- `ST_Length()` + `ST_Transform()` — дорогие функции
- Вызываются при каждом SELECT даже если не нужны
- Нет TRIGGER для оптимизации

**Надо:**
```sql
-- Хорошо:
length_m DOUBLE PRECISION NOT NULL,  -- ← Вычислено один раз в TRIGGER

CREATE TRIGGER edge_length_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION compute_edge_length();
```

### 2. **Нет граф-билдера** ❌

**Текущее:**
- Миграции просто создают таблицы
- Нет логики разбиения ways на edges по перекрёсткам
- Нет функции определения перекрёстков

**Надо:**
- Миграция 1: пустая схема (osm + graphs)
- Миграция 2: базовые таблицы (nodes, edges)
- Миграция 3: индексы и TRIGGERS
- GraphBuilder (Python): logika разбиения ways

### 3. **Дефолтные скорости не учтены** ❌

**Текущее:**
- speedlimitkmh в edges но неясно откуда берется
- Нет дефолтов (60 для улицы, 20 для двора)
- Нет logic для приоритета: OSM > config > дефолт

### 4. **Capacity вычисляется сложно** ❌

```sql
-- Плохо (текущее):
capacity INT GENERATED ALWAYS AS (
    COALESCE(lanes, 1) * CASE highwaytype
        WHEN 'motorway' THEN 2000
        ... 
    END
) STORED,
```

**Почему плохо:**
- GENERATED ALWAYS вычисляется при каждом SELECT
- Логика замешана в SQL
- Нет разделения concern'ов

**Надо:**
- Вычислить capacity ONE раз в GraphBuilder (Python)
- Сохранить как обычное число в БД
- TRIGGER пересчитывает cost/reverse_cost когда меняется current_load

### 5. **cost/reverse_cost — GENERATED ALWAYS** ❌

```sql
-- Плохо:
cost DOUBLE PRECISION GENERATED ALWAYS AS (
    length_m / (effective_speed_kmh / 3.6)
) STORED,
```

**Почему плохо:**
- pgRouting требует cost/reverse_cost но они не должны GENERATED ALWAYS
- cost должен зависеть ТОЛЬКО от current_load
- Вычисляется на каждый SELECT (дорого!)

**Надо:**
```sql
-- Хорошо:
maxspeed_kmh INT NOT NULL,      -- ← дефолт 60 или 20
current_load INT DEFAULT 0,
base_capacity INT NOT NULL,

-- ONLY эти пересчитываются через TRIGGER:
effective_speed_kmh FLOAT GENERATED ALWAYS AS (...BPR...),
cost FLOAT GENERATED ALWAYS AS (
    length_m / (effective_speed_kmh / 3.6)
),
reverse_cost FLOAT GENERATED ALWAYS AS (
    CASE WHEN oneway THEN -1.0 ELSE cost END
),
```

### 6. **Нет разделения OSM ↔ Routing Graph** ❌

**Текущее:**
- osm.ways и graphs.edges почти одно и то же
- Сложно отследить что изменилось
- Смешанная ответственность

**Надо:**
```
osm.ways    — raw OSM (источник истины, read-only)
osm.nodes   — raw OSM nodes

graphs.nodes   — перекрёстки (из osm.nodes, но отфильтрованы)
graphs.edges   — дороги разбитые по перекрёсткам + routing атрибуты
```

---

## ✅ Правильная Организация Миграций

### Новый порядок:

```
000_enable_postgis.sql                 ← остается
001_init_osm_schema.sql                ← остается (raw OSM)
002_create_graph_schema.sql (NEW!)     ← схема для графа
003_create_nodes_table.sql (NEW!)      ← перекрёстки + INDEXES
004_create_edges_table.sql (NEW!)      ← дороги + TRIGGERS
005_create_turn_restrictions.sql       ← (переименовать)
006_create_indexes.sql (NEW!)          ← все индексы
007_create_trigger_functions.sql (NEW!)← все TRIGGERS
008_add_access_restrictions.sql        ← (переместить в 008)
009_create_helper_views.sql (NEW!)     ← views для routing
```

---

## 📊 Новые Таблицы: Правильная Структура

### Миграция 002: Schema

```sql
-- 002_create_graph_schema.sql
CREATE SCHEMA IF NOT EXISTS graphs;
GRANT USAGE ON SCHEMA graphs TO diplom;
GRANT CREATE ON SCHEMA graphs TO diplom;
```

### Миграция 003: graphs.nodes

```sql
-- 003_create_nodes_table.sql
CREATE TABLE graphs.nodes (
    id SERIAL PRIMARY KEY,
    osm_node_id BIGINT UNIQUE,
    
    -- Геометрия
    geom GEOMETRY(Point, 4326) NOT NULL,
    
    -- Тип ноды
    type VARCHAR(50) DEFAULT 'intersection',
    -- 'intersection', 'uturn', 'barrier', 'traffic_signal', 'endpoint'
    
    -- Barrier information
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),
    barrier_penalty_sec INT DEFAULT 0,
    
    is_intersection BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_nodes_geom ON graphs.nodes USING GIST(geom);
CREATE INDEX idx_nodes_type ON graphs.nodes(type);
CREATE INDEX idx_nodes_osm_id ON graphs.nodes(osm_node_id);
```

### Миграция 004: graphs.edges ⭐

```sql
-- 004_create_edges_table.sql
CREATE TABLE graphs.edges (
    -- ========== PGROUTING BASE (ЖЕСТКИЕ) ==========
    id SERIAL PRIMARY KEY,
    source BIGINT NOT NULL REFERENCES graphs.nodes(id),
    target BIGINT NOT NULL REFERENCES graphs.nodes(id),
    
    -- ========== GEOMETRY & LENGTH ==========
    geom GEOMETRY(LineString, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,  -- ← Вычислено в TRIGGER!
    
    -- ========== OSM SOURCE ==========
    osm_way_id BIGINT,
    osm_tags JSONB,
    
    -- ========== ROAD ATTRIBUTES ==========
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INT DEFAULT 1,
    oneway BOOLEAN DEFAULT false,
    
    bearing_start FLOAT,
    bearing_end FLOAT,
    
    -- ========== SPEED (дефолты!) ==========
    maxspeed_kmh INT NOT NULL,
    -- Приоритет: OSM > config > дефолт[highway]
    -- Дефолты: residential=60, living_street=20, motorway=120, etc.
    
    -- ========== ACCESS & RESTRICTIONS ==========
    access_type VARCHAR(50) DEFAULT 'public',
    -- 'public', 'destination', 'private', 'no'
    
    motor_vehicle VARCHAR(50),
    -- 'yes', 'no', 'destination'
    
    service VARCHAR(50),
    -- 'driveway', 'parking', 'alley', 'parking_aisle'
    
    barrier_penalty_sec INT DEFAULT 0,
    
    -- ========== TRAFFIC & CAPACITY ==========
    base_capacity INT NOT NULL,
    -- max vehicles/hour at free-flow speed
    -- Вычислено в GraphBuilder на основе highway + lanes
    
    current_load INT DEFAULT 0,
    -- обновляется в реальном времени
    
    -- ========== DYNAMIC FIELDS (GENERATED ALWAYS) ==========
    -- ⚠️ ТОЛЬКО эти пересчитываются!
    
    effective_speed_kmh DOUBLE PRECISION GENERATED ALWAYS AS (
        -- BPR congestion function
        CASE
            WHEN current_load = 0 THEN maxspeed_kmh
            WHEN current_load <= base_capacity THEN maxspeed_kmh
            ELSE GREATEST(5.0, maxspeed_kmh * (2.0 - current_load::FLOAT / base_capacity))
        END
    ) STORED,
    
    cost DOUBLE PRECISION GENERATED ALWAYS AS (
        -- pgRouting требует! cost в секундах
        length_m / (effective_speed_kmh / 3.6)
    ) STORED,
    
    reverse_cost DOUBLE PRECISION GENERATED ALWAYS AS (
        -- pgRouting требует! -1 = нет обратного направления
        CASE WHEN oneway THEN -1.0 ELSE cost END
    ) STORED,
    
    -- ========== RF SPECIFIC ==========
    -- Нештрафуемый лимит: speed + 19 км/ч
    unstamped_speed_kmh INT GENERATED ALWAYS AS (
        maxspeed_kmh + 19
    ) STORED,
    
    -- ========== METADATA ==========
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Uniqueness
    UNIQUE(osm_way_id, source, target)
);
```

### Миграция 007: TRIGGER Functions

```sql
-- 007_create_trigger_functions.sql

-- ========== TRIGGER 1: Compute length_m ==========
CREATE OR REPLACE FUNCTION compute_edge_length()
RETURNS TRIGGER AS $$
BEGIN
    -- Вычислить length_m в метрах (Web Mercator 3857 для точности)
    NEW.length_m := ST_Length(ST_Transform(NEW.geom, 3857));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_length_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION compute_edge_length();

-- ========== TRIGGER 2: Update timestamp ==========
CREATE OR REPLACE FUNCTION update_edge_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_updated_at_trigger
BEFORE UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION update_edge_timestamp();

-- ========== TRIGGER 3: Validate consistency ==========
CREATE OR REPLACE FUNCTION validate_edge_consistency()
RETURNS TRIGGER AS $$
BEGIN
    -- Проверка 1: source != target
    IF NEW.source = NEW.target THEN
        RAISE EXCEPTION 'Edge cannot start and end at the same node: %', NEW.id;
    END IF;
    
    -- Проверка 2: length_m > 0
    IF NEW.length_m <= 0 THEN
        RAISE EXCEPTION 'Edge length must be > 0: %', NEW.id;
    END IF;
    
    -- Проверка 3: maxspeed_kmh > 0
    IF NEW.maxspeed_kmh <= 0 THEN
        RAISE EXCEPTION 'maxspeed_kmh must be > 0: %', NEW.id;
    END IF;
    
    -- Проверка 4: base_capacity > 0
    IF NEW.base_capacity <= 0 THEN
        RAISE EXCEPTION 'base_capacity must be > 0: %', NEW.id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_validate_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION validate_edge_consistency();
```

### Миграция 009: Helper Views

```sql
-- 009_create_helper_views.sql

-- View 1: Edges with congestion ratio
CREATE OR REPLACE VIEW graphs.edges_with_congestion AS
SELECT 
    e.*,
    CASE 
        WHEN e.base_capacity > 0 
        THEN e.current_load::FLOAT / e.base_capacity
        ELSE 0.0 
    END as congestion_ratio
FROM graphs.edges e;

-- View 2: Adjacency list for routing
CREATE OR REPLACE VIEW graphs.adjacency_list AS
SELECT 
    source as node_id,
    array_agg(id) as outgoing_edge_ids
FROM graphs.edges
GROUP BY source;

-- View 3: Intersection analysis
CREATE OR REPLACE VIEW graphs.intersection_analysis AS
SELECT 
    n.id,
    n.osm_node_id,
    COUNT(e.id) as degree,
    array_agg(DISTINCT e.highway) as highway_types,
    array_agg(DISTINCT e.access_type) as access_types
FROM graphs.nodes n
LEFT JOIN graphs.edges e ON n.id = e.source OR n.id = e.target
GROUP BY n.id, n.osm_node_id;

-- View 4: Turn restrictions analysis
CREATE OR REPLACE VIEW graphs.turn_restriction_summary AS
SELECT 
    v.vianode,
    tr.restrictiontype,
    COUNT(*) as count
FROM graphs.turn_restrictions tr
LEFT JOIN graphs.nodes v ON tr.vianode = v.id
GROUP BY v.vianode, tr.restrictiontype;
```

---

## 🐍 GraphBuilder: Python Логика

### Шаг 1: Найти перекрёстки

```python
# src/server/services/graph_builder/graph_builder.py

async def _find_intersections(self, conn):
    """
    Найти узлы которые являются перекрёстками.
    
    Перекрёсток = узел который используется 2+ ways или 
                  узел на конце way (если не используется больше нигде)
    """
    query = """
    SELECT 
        node_id,
        COUNT(DISTINCT way_id) as way_count
    FROM osm.way_nodes
    GROUP BY node_id
    HAVING COUNT(DISTINCT way_id) >= 2
    """
    
    intersections = await conn.fetch(query)
    return {row['node_id'] for row in intersections}
```

### Шаг 2: Создать nodes

```python
async def _create_nodes(self, conn, intersections):
    """Создать graphs.nodes из перекрёстков."""
    
    query = """
    INSERT INTO graphs.nodes (osm_node_id, geom, type, is_intersection)
    SELECT 
        id as osm_node_id,
        geom,
        'intersection' as type,
        true as is_intersection
    FROM osm.nodes
    WHERE id = ANY($1)
    ON CONFLICT (osm_node_id) DO NOTHING
    RETURNING id
    """
    
    rows = await conn.fetch(query, list(intersections))
    logger.info(f"Created {len(rows)} nodes")
```

### Шаг 3: Разбить ways на edges

```python
async def _split_ways_into_edges(self, conn, osm_ways_data):
    """
    Разбить ways на segments по перекрёсткам.
    
    Логика:
    1. Для каждого way
    2. Получить все узлы на этом way
    3. Найти перекрёстки в этом way
    4. Разбить way на segments между перекрёсткам
    5. Создать edge для каждого segment
    """
    
    edges_to_insert = []
    
    for way in osm_ways_data:
        way_id = way['id']
        nodes = way['nodes']  # упорядоченный list узлов
        geometry = way['geometry']
        
        # Найти перекрёстки в этом way
        intersection_indices = []
        for i, node_id in enumerate(nodes):
            if node_id in self.intersections:
                intersection_indices.append(i)
        
        # Если нет перекрёстков → один edge
        if len(intersection_indices) <= 1:
            start_idx, end_idx = 0, len(nodes) - 1
            edges_to_insert.append(self._create_edge_from_segment(
                way, start_idx, end_idx, geometry, nodes
            ))
        else:
            # Разбить на segments
            for i in range(len(intersection_indices) - 1):
                start_idx = intersection_indices[i]
                end_idx = intersection_indices[i + 1]
                edges_to_insert.append(self._create_edge_from_segment(
                    way, start_idx, end_idx, geometry, nodes
                ))
    
    # Batch insert
    query = """
    INSERT INTO graphs.edges (
        osm_way_id, source, target, geom, 
        highway, name, lanes, oneway, maxspeed_kmh, 
        access_type, motor_vehicle, service, base_capacity,
        osm_tags
    ) VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326), 
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    await conn.executemany(query, edges_to_insert)
    logger.info(f"Created {len(edges_to_insert)} edges")
```

### Шаг 4: Установить speeds с дефолтами

```python
# DEFAULT SPEEDS
DEFAULT_SPEEDS = {
    'motorway': 120,
    'motorway_link': 80,
    'trunk': 100,
    'primary': 90,
    'secondary': 80,
    'tertiary': 60,
    'residential': 60,        # ← город
    'living_street': 20,      # ← двор
    'unclassified': 50,
    'service': 20,            # ← сервис, проезд
    'track': 30,
    'road': 50,
}

async def _set_speeds_with_defaults(self, conn):
    """
    Установить maxspeed_kmh с приоритетом:
    1. OSM maxspeed tag (если есть и валидна)
    2. Config override
    3. DEFAULT_SPEEDS[highway]
    """
    
    # Шаг 1: OSM maxspeed (если есть)
    query1 = """
    UPDATE graphs.edges SET maxspeed_kmh = (osm_tags->>'maxspeed')::INT
    WHERE osm_tags ? 'maxspeed' 
      AND (osm_tags->>'maxspeed') ~ '^[0-9]+$'
      AND maxspeed_kmh IS NULL
    """
    await conn.execute(query1)
    
    # Шаг 2: Дефолты по highway type
    for highway, speed in DEFAULT_SPEEDS.items():
        query = """
        UPDATE graphs.edges 
        SET maxspeed_kmh = $1 
        WHERE highway = $2 AND maxspeed_kmh IS NULL
        """
        await conn.execute(query, speed, highway)
    
    logger.info("Set speeds with defaults")
```

### Шаг 5: Установить capacity

```python
CAPACITY_LOOKUP = {
    # (highway, lanes) -> vehicles/hour
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
    ('living_street', None): 400,
    ('service', None): 300,
}

async def _set_capacity(self, conn):
    """Установить base_capacity на основе highway + lanes."""
    
    for (highway, lanes), capacity in CAPACITY_LOOKUP.items():
        if lanes is None:
            query = """
            UPDATE graphs.edges 
            SET base_capacity = $1 
            WHERE highway = $2
            """
            await conn.execute(query, capacity, highway)
        else:
            query = """
            UPDATE graphs.edges 
            SET base_capacity = $1 
            WHERE highway = $2 AND lanes = $3
            """
            await conn.execute(query, capacity, highway, lanes)
    
    logger.info("Set capacity")
```

---

## 📝 Итоги Правильной Организации

### ✅ Что изменилось:

1. **TRIGGER вычисляет length_m один раз** (при INSERT/UPDATE)
   - Не вычисляется при каждом SELECT

2. **cost/reverse_cost пересчитываются ТОЛЬКО когда current_load меняется**
   - Дорогие вычисления минимизированы

3. **Grapher-builder в Python**
   - Логика разбиения ways на edges
   - Дефолтные скорости с приоритетом
   - Capacity на основе highway + lanes

4. **Четкое разделение:**
   - osm.* — raw OSM (read-only)
   - graphs.* — routing граф (dynamic)

5. **Миграции организованы логически**
   - Одна ответственность за миграцию
   - Легко отследить изменения

### ✅ Производительность:

| Операция | До | После |
|----------|----|-|
| SELECT edges | TRIGGER + GENERATED для каждой | TRIGGER только при UPDATE |
| cost пересчет | При каждом SELECT | При каждом UPDATE current_load |
| Разбиение ways | Нет логики | Python logic, чистая |
| Default speeds | Нет | Config + DEFAULT_SPEEDS |

---

## 🚀 Что Делать Дальше

1. Создать миграции (002-009) по новой спецификации
2. Написать GraphBuilder (Python) с 5 шагами
3. Протестировать на реальных OSM данных
4. Пересчитать statistics

**Это правильная production-ready архитектура!** ✅
