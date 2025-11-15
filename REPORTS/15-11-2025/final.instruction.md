<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Финальная архитектурная инструкция для МАС навигации

**Дата:** 15 ноября 2025
**Статус:** Готово к разработке (R\&D-1 → R\&D-2)
**Назначение:** Полная спецификация архитектуры, нюансы, подводные камни, best practices

***

## 🎯 Общие принципы архитектуры

### Ключевые решения (финальные)

1. **Routing Engine:** pgRouting (динамические веса per-edge).
2. **Simulation:** Собственная (capacity/congestion, не SUMO).
3. **Graph Storage:** PostgreSQL + PostGIS (единый источник правды).
4. **MVT Generation:** On-the-fly из PostGIS (не pre-generated tiles).
5. **Agent State:** Memory-first (numpy arrays), batch sync в БД каждые 5 сек.
6. **Scaling:** 1 agent (R\&D-1) → 1000 agents (R\&D-2) через AgentPool + vectorization.

***

## 📦 Структура сущностей

### 1. DataAcquisitionService

**Ответственность:**

- Скачать OSM данные (Overpass API или PBF файлы).
- Скачать растровые tiles (для фона карты).
- Положить в БД (OSM ways) и файловую систему (растровые tiles).

**Критичные нюансы:**

#### ❗ **Tiles storage: Разделить растровые vs векторные**

```
Растровые tiles (картинки фона):
  - НЕ в БД (раздует размер, медленнее файловой системы)
  - Храним в файловой системе: /data/tiles/{z}/{x}/{y}.png
  - Server отдаёт через StaticFiles или nginx
  - Кэш браузера: Cache-Control: max-age=86400 (24 часа)

MVT tiles (векторный граф дорог):
  - НЕ храним (генерация on-the-fly из PostGIS)
  - GraphService вызывает ST_AsMVT() при запросе
  - Кэш браузера + опционально Redis (если нужно)
```

**Подводный камень:**

```python
# НЕПРАВИЛЬНО (медленно):
def get_tile(z, x, y):
    return db.query("SELECT image FROM tiles WHERE z=? AND x=? AND y=?")

# ПРАВИЛЬНО (быстро):
def get_tile(z, x, y):
    return send_file(f"/data/tiles/{z}/{x}/{y}.png")
```

**Best practice:**

- Один PBF файл (Geofabrik) → DataAcquisitionService импортирует → GraphService строит из него граф + MVT.
- Никогда не смешивайте источники (Overpass vs PBF) — это гарантирует идентичность данных.

***

### 2. GraphService

**Ответственность:**

- Парсинг OSM (PBF/XML) → nodes, edges (preprocessing, один раз).
- Вычисление bearing, capacity (preprocessing).
- Генерация MVT tiles (runtime, on-the-fly).
- Отдача графа по bbox для GUI (GeoJSON или MVT).

**Критичные нюансы:**

#### ❗ **Bearing для multi-segment edges**

**Проблема:**

```
Edge: 5 км, LineString с 20 точками, изгибы 0° → 90°.
Если храним только bearing_start (первый сегмент):
  → Агент на 90% ребра думает, что едет на North (0°),
  → Но фактически едет на East (90°) → неправильный угол поворота!
```

**Решение (R\&D-1, упрощение):**

```sql
-- Храним bearing_end (последний сегмент, перед выходом)
ALTER TABLE edges ADD COLUMN bearing_end FLOAT;

UPDATE edges SET bearing_end = degrees(
  ST_Azimuth(
    ST_PointN(geom, ST_NumPoints(geom) - 1),  -- Предпоследняя точка
    ST_EndPoint(geom)                           -- Последняя точка
  )
);
```

**Почему это правильно:**

- Агент тормозит **перед выходом** с ребра (на последних 10% длины).
- Угол поворота = `next_edge.bearing_start - current_edge.bearing_end`.

**Решение (R\&D-2, точное):**

```sql
-- Храним оба bearing
ALTER TABLE edges 
  ADD COLUMN bearing_start FLOAT,
  ADD COLUMN bearing_end FLOAT;

-- Или: вычисляем динамически на основе position_frac
-- (если ребро короткое <500м, разница незначительна)
```

**Best practice:**

- R\&D-1: используйте `bearing_end` (достаточно для proof-of-concept).
- R\&D-2: добавьте `bearing_start` для точности (или динамический расчёт).

***

#### ❗ **MVT generation: Pre-computed geom_3857**

**Обязательно:**

```sql
-- Колонка для Web Mercator (MVT работает в EPSG:3857)
ALTER TABLE osm.ways ADD COLUMN geom_3857 geometry(LineString, 3857);

-- Trigger для auto-sync при INSERT/UPDATE
CREATE OR REPLACE FUNCTION sync_geom_3857()
RETURNS TRIGGER AS $$
BEGIN
  NEW.geom_3857 := ST_Transform(NEW.geom, 3857);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sync_geom_3857
BEFORE INSERT OR UPDATE ON osm.ways
FOR EACH ROW EXECUTE FUNCTION sync_geom_3857();

-- Spatial index (критично для производительности!)
CREATE INDEX idx_osm_ways_geom_3857 ON osm.ways USING GIST(geom_3857);
```

**Почему критично:**

- `ST_Transform(geom, 3857)` на каждом запросе MVT tile = **медленно** (~10-20ms per tile).
- Pre-computed `geom_3857` + spatial index = **быстро** (~2-5ms per tile).

**Best practice:**

- Всегда используйте trigger для auto-sync (не забудете обновить при изменении `geom`).
- Создавайте spatial index **после** заполнения таблицы (иначе каждый INSERT будет обновлять индекс, медленно).

***

### 3. RoutingCoordinator (pgRouting)

**Ответственность:**

- Получить K маршрутов через pgRouting.
- Обеспечить diversity (чтобы маршруты были разными).
- Учесть turn penalties (через cost в SQL).
- Snap to road (через pgr_findClosestEdge).

**Критичные нюансы:**

#### ❗ **K-shortest paths: Diversity penalties**

**Проблема Yens алгоритма:**

```sql
-- Yens (pgr_ksp) может вернуть:
Route 1: A → B → C → D (10 км)
Route 2: A → B → C' → D (10.1 км, почти то же!)
Route 3: A → B → C'' → D (10.2 км, опять похоже!)

-- Все маршруты проходят через B, C → не diversity!
```

**Решение: SQL функция с diversity penalties**

```sql
CREATE OR REPLACE FUNCTION get_k_routes_with_diversity(
  start_node BIGINT,
  end_node BIGINT,
  k INT DEFAULT 3,
  penalty_factor FLOAT DEFAULT 1.5,
  diversity_threshold FLOAT DEFAULT 0.7
) RETURNS TABLE(route_index INT, seq INT, node BIGINT, edge BIGINT, cost FLOAT) AS $$
DECLARE
  used_edges BIGINT[] := ARRAY[]::BIGINT[];
  route_edges BIGINT[];
  overlap_ratio FLOAT;
  i INT;
BEGIN
  FOR i IN 1..k LOOP
    -- Запрос с penalties для уже использованных рёбер
    RETURN QUERY
    SELECT 
      i AS route_index,
      path.seq,
      path.node,
      path.edge,
      path.cost
    FROM pgr_dijkstra(
      format('
        SELECT id, source, target,
               CASE 
                 WHEN id = ANY($1) THEN cost * %s  -- Penalty!
                 ELSE cost
               END AS cost
        FROM edges
        WHERE cost IS NOT NULL
      ', penalty_factor),
      start_node,
      end_node,
      directed := true
    ) AS path;
    
    -- Собираем рёбра найденного маршрута
    SELECT array_agg(edge) INTO route_edges
    FROM pgr_dijkstra(...) WHERE edge IS NOT NULL;
    
    -- Проверяем diversity
    SELECT 
      COALESCE(
        (SELECT count(*) FROM unnest(route_edges) AS e WHERE e = ANY(used_edges))::FLOAT / 
        NULLIF(array_length(route_edges, 1), 0),
        0
      ) INTO overlap_ratio;
    
    -- Если overlap < threshold → добавляем маршрут
    IF overlap_ratio < (1.0 - diversity_threshold) THEN
      used_edges := used_edges || route_edges;
    ELSE
      -- Увеличиваем penalty ещё сильнее (чтобы найти ещё более разный маршрут)
      penalty_factor := penalty_factor * 1.5;
    END IF;
  END LOOP;
END;
$$ LANGUAGE plpgsql;
```

**Вызов:**

```python
routes = db.query("""
  SELECT * FROM get_k_routes_with_diversity(
    start_node := 12345,
    end_node := 67890,
    k := 3,
    penalty_factor := 1.5,
    diversity_threshold := 0.7
  )
  ORDER BY route_index, seq;
""")
```

**Подводный камень:**

- Diversity penalties **не гарантируют** K маршрутов (может быть меньше, если граф сильно ограничен).
- Проверяйте `len(routes)` и обрабатывайте случай, когда routes < K.

**Best practice:**

- Penalty factor = 1.5 (R\&D-1, умеренно).
- Diversity threshold = 0.7 (70% уникальных рёбер).
- Для R\&D-2: добавьте параметры в конфиг (YAML).

***

#### ❗ **Turn penalties в pgRouting**

**Проблема:** pgRouting **не считает** turn penalties автоматически (в отличие от OSRM/Valhalla).

**Решение: Двухуровневый подход**

**Уровень 1: Cost в маршрутизации (RoutingCoordinator)**

```sql
-- Добавляем turn_penalty в cost при построении маршрута
SELECT id, source, target,
       length_m / effective_speed AS base_cost,
       
       -- Turn penalty (если известен угол между предыдущим и текущим ребром)
       -- Вычисляется через JOIN с предыдущим ребром в пути
       CASE 
         WHEN abs(bearing_start - prev_edge.bearing_end) < 30 THEN 0
         WHEN abs(bearing_start - prev_edge.bearing_end) < 60 THEN 2
         WHEN abs(bearing_start - prev_edge.bearing_end) < 120 THEN 7.5
         WHEN abs(bearing_start - prev_edge.bearing_end) < 150 THEN 12
         ELSE 20
       END AS turn_penalty,
       
       base_cost + turn_penalty AS cost
FROM edges;
```

**Проблема:** В `pgr_dijkstra` нельзя обратиться к предыдущему ребру пути (нет контекста).

**Workaround:** Post-processing маршрута (после получения от pgRouting):

```python
def add_turn_penalties(route_edges):
    """Добавить turn penalties после построения маршрута."""
    total_time = 0
    
    for i, edge in enumerate(route_edges):
        # Базовое время
        total_time += edge.length_m / edge.effective_speed
        
        # Turn penalty (если есть следующее ребро)
        if i + 1 < len(route_edges):
            next_edge = route_edges[i + 1]
            angle_diff = abs(next_edge.bearing_start - edge.bearing_end)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            
            turn_penalty_sec = get_turn_penalty(angle_diff)
            total_time += turn_penalty_sec
    
    return total_time
```

**Уровень 2: Физика движения (Agent)**

```python
# Агент замедляется на повороте (при движении)
if agent.position_frac > 0.9:  # Последние 10% ребра
    next_edge = route[agent.route_index + 1]
    angle_diff = abs(next_edge.bearing_start - agent.current_edge.bearing_end)
    
    # Максимальная скорость на повороте
    turn_speed_limit = {
        range(0, 30): 100,    # Прямо
        range(30, 60): 60,    # Slight
        range(60, 120): 40,   # Turn
        range(120, 150): 20,  # Sharp
        range(150, 181): 10   # U-turn
    }
    
    agent.speed_kmh = min(agent.speed_kmh, turn_speed_limit[angle_diff])
```

**Best practice:**

- R\&D-1: Post-processing маршрута (проще, достаточно для travel time estimation).
- R\&D-2: Agent физика (реалистично, для симуляции движения).

***

### 4. SimulationCore

**Ответственность:**

- Управление временем (FPS, timestep).
- Обновление позиций агентов (vectorized, numpy).
- Сбор current_load на рёбрах (batch).
- Пересчёт effective_speed (batch SQL UPDATE).
- Broadcast state через WebSocket.

**Критичные нюансы:**

#### ❗ **Memory vs Database sync**

**Правило:** Memory — primary source of truth. БД — persistence.

**Схема:**

```
SimulationCore:
  - AgentBatch: numpy arrays (id, lat, lon, speed, edge_id, position_frac)
  - Обновление: каждый tick (50ms @ 20 FPS)
  - Vectorized operations (numpy)

PostgreSQL:
  - agents table: snapshot каждые 5 секунд
  - edges.current_load: batch UPDATE каждые 1-5 секунд
  - WAL (Write-Ahead Log): Redis Stream или COPY TO temp file

API Server:
  - GET /agents/{id} → читает из SimulationCore.memory (real-time)
  - WebSocket /stream → broadcast из SimulationCore.memory

TelemetryCollector:
  - Получает AgentSnapshot[] из SimulationCore.memory (не БД!)
  - Детект телепортов, аномалий → Loki
```

**Подводный камень:**

```python
# НЕПРАВИЛЬНО (медленно для 1000 агентов):
for agent in agents:
    db.execute("UPDATE agents SET lat=?, lon=?, speed=? WHERE id=?", 
               agent.lat, agent.lon, agent.speed, agent.id)

# ПРАВИЛЬНО (batch, ~30ms для 1000 агентов):
values = [(a.lat, a.lon, a.speed, a.id) for a in agents]
db.execute_batch("""
  UPDATE agents AS a SET lat=c.lat, lon=c.lon, speed=c.speed
  FROM (VALUES %s) AS c(lat, lon, speed, id)
  WHERE a.id = c.id
""", values)
```

**Best practice:**

- Snapshot в БД каждые 5-10 секунд (не каждый tick).
- Частота batch UPDATE edges.current_load: 1-5 секунд (зависит от FPS симуляции).
- WAL для crash recovery: Redis Stream (быстрее, но нужен Redis) или PostgreSQL COPY (медленнее, но встроено).

***

#### ❗ **Capacity и effective_speed**

**Два варианта (из вашего вопроса):**

**Вариант 1: safe_s = const (R\&D-1, упрощение)**

```python
SAFE_DISTANCE_SEC = 3.0
VEHICLE_LENGTH_M = 5.0

def calculate_base_capacity(length_m, lanes, max_v_kmh):
    max_v_ms = max_v_kmh / 3.6
    safe_m = SAFE_DISTANCE_SEC * max_v_ms + VEHICLE_LENGTH_M
    return int((length_m * lanes) / safe_m)

def calculate_effective_speed_simple(max_v_kmh, actual_load, base_capacity):
    congestion = actual_load / base_capacity
    if congestion <= 1.0:
        return max_v_kmh
    else:
        return max(5.0, max_v_kmh * (2.0 - congestion))
```

**SQL:**

```sql
-- Preprocessing
UPDATE edges SET base_capacity = (
  length_m * lanes / (3.0 * (maxspeed_kmh / 3.6) + 5.0)
);

-- Runtime
UPDATE edges SET effective_speed = (
  maxspeed_kmh * GREATEST(0.05, 2.0 - current_load::float / base_capacity)
)
WHERE current_load > 0;
```

**Вариант 2: safe_s = f(v) (R\&D-2, реалистично)**

```python
def safe_distance_sec_smooth(v_kmh):
    """ПДД РФ: 1 сек (<40), 2 сек (40-80), 3 сек (80+)"""
    if v_kmh < 40:
        return 1.0
    elif v_kmh < 80:
        return 1.0 + (v_kmh - 40) / 40
    else:
        return 2.0 + min(1.0, (v_kmh - 80) / 40)

def calculate_effective_speed_realistic(max_v_kmh, actual_load, length_m, lanes):
    """Бинарный поиск: найти v такое, что capacity(v) = actual_load."""
    capacity_at_max = calculate_capacity_at_speed(length_m, lanes, max_v_kmh)
    
    if actual_load <= capacity_at_max:
        return max_v_kmh
    
    low_v, high_v = 5.0, max_v_kmh
    for _ in range(20):
        mid_v = (low_v + high_v) / 2
        cap_mid = calculate_capacity_at_speed(length_m, lanes, mid_v)
        
        if cap_mid < actual_load:
            high_v = mid_v
        else:
            low_v = mid_v
    
    return (low_v + high_v) / 2
```

**Рекомендация:**

- R\&D-1: Вариант 1 (формула линейная, SQL-friendly, быстро).
- R\&D-2: Вариант 2 (реалистично, соответствует traffic flow theory, но сложнее).

**Подводный камень:**

- При congestion > 2.0 (двойная перегрузка) в Варианте 1: `effective_speed = max(5, max_v * (2-2)) = 5 км/ч`.
- Это минимум (стоим), но на практике может быть и 0 (полная остановка).
- Решение: `min_speed = 5 км/ч` (константа из конфига).

***

### 5. Agent (легковесный)

**Ответственность:**

- Хранение состояния (lat, lon, speed, current_edge, position_frac).
- Движение по маршруту (обновление position_frac каждый tick).
- Реакция на команды (start, stop, reroute).

**Критичные нюансы:**

#### ❗ **Физика движения: Ускорение и торможение**

**Проблема:**

```python
# Наивная реализация (мгновенное изменение скорости):
agent.speed = edge.effective_speed

# Результат: агент "телепортируется" (скорость 0 → 100 км/ч за 1 тик)
```

**Решение: Зоны ускорения/торможения**

```python
class Agent:
    ACCELERATION_ZONE = 0.05  # Первые 5% ребра
    DECELERATION_ZONE = 0.10  # Последние 10% ребра
    
    def update_position(self, dt):
        """Обновить позицию за dt секунд."""
        
        # 1. Вычислить целевую скорость
        target_speed = self.current_edge.effective_speed
        
        # 2. Если в зоне ускорения/торможения
        if self.position_frac < self.ACCELERATION_ZONE:
            # Ускорение: 0 → target_speed линейно
            progress = self.position_frac / self.ACCELERATION_ZONE
            self.speed = target_speed * progress
        
        elif self.position_frac > (1.0 - self.DECELERATION_ZONE):
            # Торможение перед поворотом
            next_edge = self.route[self.route_index + 1]
            angle_diff = abs(next_edge.bearing_start - self.current_edge.bearing_end)
            turn_speed_limit = get_turn_speed_limit(angle_diff)
            
            progress = (1.0 - self.position_frac) / self.DECELERATION_ZONE
            self.speed = turn_speed_limit + (self.speed - turn_speed_limit) * progress
        
        else:
            # Свободное движение: следуем effective_speed
            self.speed = target_speed
        
        # 3. Обновить position_frac
        distance_m = self.speed * dt / 3.6  # км/ч → м/с
        self.position_frac += distance_m / self.current_edge.length_m
        
        # 4. Переход на следующее ребро
        if self.position_frac >= 1.0:
            self.position_frac = 0.0
            self.route_index += 1
            self.current_edge = self.route[self.route_index]
```

**Best practice:**

- ACCELERATION_ZONE = 5% (реалистично для города).
- DECELERATION_ZONE = 10% (агент замедляется заранее перед поворотом).
- Параметры → конфиг (YAML).

**Подводный камень:**

- Если `dt` слишком большой (например, 5 сек), агент может "перепрыгнуть" ребро (position_frac > 1.0 сильно).
- Решение: ограничьте `dt` (максимум 1 сек) или разбейте шаг на sub-steps.

***

#### ❗ **TelemetryCollector: Детект телепортов**

**Логика:**

```python
def detect_teleport(agent, prev_snapshot):
    """Проверить: не телепортировался ли агент?"""
    
    # Ожидаемое расстояние за dt
    dt = current_time - prev_snapshot.timestamp
    expected_distance_m = agent.speed * dt / 3.6
    
    # Фактическое расстояние
    actual_distance_m = haversine(
        prev_snapshot.lat, prev_snapshot.lon,
        agent.lat, agent.lon
    )
    
    # Порог: допускаем погрешность 50%
    if actual_distance_m > expected_distance_m * 1.5:
        logger.warning(
            f"Teleport detected: agent={agent.id}, "
            f"expected={expected_distance_m:.1f}m, "
            f"actual={actual_distance_m:.1f}m"
        )
        return True
    
    return False
```

**Best practice:**

- TelemetryCollector работает **in-memory** (SimulationCore передаёт снапшоты).
- Детект телепорта **отключается** в production (для снижения overhead), но полезен в разработке.
- Логирование → Loki (не БД).

***

### 6. Coordinator (МАС логика)

**Ответственность:**

- Анализ congestion (глобальная картина сети).
- Распределение маршрутов (K альтернатив для каждого агента).
- Приоритизация (спец. транспорт).
- Балансировка нагрузки (min max_congestion или min total_time).

**Критичные нюансы:**

#### ❗ **Priority агентов**

**Логика (из answers.md):**

```python
# Priority levels:
#  0-9:   Обычный транспорт (легковые авто)
#  10-19: Общественный транспорт (автобусы)
#  20-29: Спец. транспорт (скорая, пожарная, полиция)

def get_route_with_priority(agent, start, dest, edges):
    """Получить маршрут с учётом priority."""
    
    if agent.priority >= 20:
        # Спец. транспорт: игнорируем congestion
        route = routing_provider.route(
            start, dest,
            cost_function="length / maxspeed"  # Без учёта current_load!
        )
    else:
        # Обычный транспорт: учитываем congestion
        route = routing_provider.route(
            start, dest,
            cost_function="length / effective_speed"  # С учётом current_load
        )
    
    return route
```

**R\&D-2 (advanced):**

```python
# Координатор "расчищает" дорогу для спец. транспорта
def coordinate_with_priority(agents, edges):
    """Распределить маршруты с учётом priority."""
    
    # 1. Сначала маршруты для high-priority агентов
    priority_agents = [a for a in agents if a.priority >= 20]
    for agent in priority_agents:
        route = get_route_with_priority(agent, ...)
        agent.route = route
    
    # 2. Затем для low-priority агентов (избегаем рёбер из priority маршрутов)
    normal_agents = [a for a in agents if a.priority < 20]
    for agent in normal_agents:
        # Получаем K маршрутов с penalties на рёбра из priority маршрутов
        routes = routing_provider.k_routes(
            ...,
            penalty_edges=[edge.id for route in priority_routes for edge in route]
        )
        agent.route = select_best_route(routes, edges)
```

**Best practice:**

- R\&D-1: Priority через cost_function (проще).
- R\&D-2: Координатор "расчищает" дорогу (научная новизна для диссертации).

***

#### ❗ **Rerouting frequency**

**Три стратегии:**

**1. Fixed interval (простая, R\&D-1)**

```python
# Пересчитываем маршруты каждые 30 секунд для ВСЕХ агентов
if simulation_time % 30 == 0:
    for agent in agents:
        new_route = coordinator.get_route(agent.position, agent.dest)
        agent.route = new_route
```

**Проблема:** Много CPU (1000 агентов × 30 сек = overhead).

**2. Event-driven (оптимальная, R\&D-2)**

```python
# Пересчитываем только если затор впереди
for agent in agents:
    next_edges = agent.route[agent.route_index : agent.route_index + 3]
    
    for edge_id in next_edges:
        edge = edges[edge_id]
        if edge.current_load / edge.capacity > 0.8:  # Затор!
            new_route = coordinator.get_route(agent.position, agent.dest)
            agent.route = new_route
            break
```

**Плюсы:** Агенты реагируют сразу (как только видят затор).

**3. Гибрид (рекомендуемая)**

```python
# Check каждые 5 секунд, но reroute только если нужно
if simulation_time % 5 == 0:
    agents_to_reroute = []
    
    for agent in agents:
        if needs_rerouting(agent, edges):
            agents_to_reroute.append(agent)
    
    # Batch rerouting (параллельно, ProcessPool)
    with ProcessPool(8) as pool:
        new_routes = pool.map(
            lambda a: coordinator.get_route(a.position, a.dest),
            agents_to_reroute
        )
    
    for agent, route in zip(agents_to_reroute, new_routes):
        agent.route = route
```

**Best practice:**

- R\&D-1: Fixed interval (30 сек, проще).
- R\&D-2: Гибрид (check 5 сек, reroute если нужно).

***

## 🔧 Конфигурация (YAML best practices)

### Файл: `config/simulation.yaml`

```yaml
simulation:
  # FPS и timestep
  fps: 20                    # ticks per second
  timestep_sec: 0.05         # 1 / fps
  
  # Capacity formula
  capacity:
    vehicle_length_m: 5.0
    mode: simple             # simple | realistic
    simple:
      safe_distance_sec: 3.0
      min_speed_kmh: 5.0
    realistic:
      safe_distance_function:
        - {speed_kmh: 0, safe_sec: 1.0}
        - {speed_kmh: 40, safe_sec: 1.0}
        - {speed_kmh: 80, safe_sec: 2.0}
        - {speed_kmh: 120, safe_sec: 3.0}
      binary_search_iterations: 20
      min_speed_kmh: 5.0
  
  # Effective_speed formula
  effective_speed:
    formula: bpr             # bpr | linear
    bpr:
      alpha: 0.7
      beta: 1.5
    linear:
      congestion_threshold: 1.0
  
  # Agent physics
  agent:
    acceleration_zone: 0.05  # 5% начала ребра
    deceleration_zone: 0.10  # 10% конца ребра
    turn_speed_limits:
      straight: 100          # < 30°
      slight: 60             # 30-60°
      turn: 40               # 60-120°
      sharp: 20              # 120-150°
      uturn: 10              # 150-180°
  
  # Sync intervals
  sync:
    agents_to_db_sec: 5      # Snapshot в БД
    edges_load_update_sec: 1 # Batch UPDATE current_load
    wal_buffer_size: 1000    # WAL буфер (агентов)
  
  # Rerouting
  rerouting:
    strategy: hybrid         # fixed | event_driven | hybrid
    fixed:
      interval_sec: 30
    event_driven:
      congestion_threshold: 0.8
      lookahead_edges: 3
    hybrid:
      check_interval_sec: 5
      congestion_threshold: 0.8
  
  # Telemetry
  telemetry:
    enable_teleport_detection: true  # false в production
    teleport_threshold: 1.5          # 150% от ожидаемого расстояния
```


***

## 📊 Метрики и тестирование

### Baseline vs MAS (для диссертации)

**Сценарии:**

1. **Bottleneck Test:**
    - 100 агентов, все OD пары через один узел (искусственный затор).
    - Baseline: каждый строит кратчайший путь (пробка на узле).
    - MAS: координатор распределяет по K маршрутам (меньше пробка).
2. **Moscow MKAD Test:**
    - 1000 агентов, random OD пары (Москва МКАД).
    - Baseline vs MAS: avg_travel_time, max_congestion, throughput.
3. **Priority Test:**
    - 500 обычных агентов + 10 спец. транспорт (priority=20).
    - MAS: координатор расчищает дорогу для спец. транспорта.

**Метрики:**

```python
# Prometheus metrics (экспортируем из SimulationCore)
metrics = {
    "avg_travel_time_sec": mean([a.travel_time for a in finished_agents]),
    "max_congestion": max([e.current_load / e.capacity for e in edges]),
    "throughput": len(finished_agents) / simulation_time_sec,
    "routing_time_ms": histogram([...]),
    "simulation_step_ms": histogram([...]),
}
```

**Ожидаемый результат (для защиты):**

```
MAS vs Baseline:
  - avg_travel_time: -20-30% (МАС быстрее)
  - max_congestion: -30-50% (МАС меньше пробок)
  - throughput: +10-20% (МАС больше агентов достигают цели)
```

**Если нет выигрыша → МАС бесполезен** (не защитите диссертацию).

***

## ⚠️ Подводные камни (финальный чеклист)

### 1. PostgreSQL connection pooling

```python
# НЕПРАВИЛЬНО (новое соединение на каждый запрос):
def query():
    conn = psycopg2.connect(DATABASE_URL)
    return conn.execute("SELECT ...")

# ПРАВИЛЬНО (пул соединений):
from psycopg2 import pool
connection_pool = pool.SimpleConnectionPool(minconn=5, maxconn=20, dsn=DATABASE_URL)

def query():
    conn = connection_pool.getconn()
    try:
        return conn.execute("SELECT ...")
    finally:
        connection_pool.putconn(conn)
```


### 2. Spatial indexes (критично!)

```sql
-- ОБЯЗАТЕЛЬНО создать после заполнения таблицы
CREATE INDEX idx_edges_geom ON edges USING GIST(geom);
CREATE INDEX idx_edges_geom_3857 ON edges USING GIST(geom_3857);

-- Проверить использование индекса:
EXPLAIN ANALYZE SELECT * FROM edges WHERE geom && ST_MakeEnvelope(...);
-- Должно быть: "Index Scan using idx_edges_geom"
-- Если "Seq Scan" → индекс не используется (медленно!)
```


### 3. NumPy vectorization (для 1000 агентов)

```python
# НЕПРАВИЛЬНО (цикл в Python, медленно):
for agent in agents:
    agent.position_frac += agent.speed * dt / agent.edge_length

# ПРАВИЛЬНО (векторизация, быстро):
agents.position_frac += agents.speed * dt / agents.edge_length  # numpy
```


### 4. WebSocket backpressure

```python
# Если клиент медленный (не успевает обрабатывать сообщения):
# → очередь сообщений растёт → memory leak

# Решение: ограничить очередь
@app.websocket("/stream")
async def stream(websocket: WebSocket):
    queue = asyncio.Queue(maxsize=10)  # Максимум 10 сообщений
    
    try:
        while True:
            state = await queue.get()
            await websocket.send_json(state)
    except asyncio.QueueFull:
        # Клиент не успевает → дропаем старые сообщения
        queue.get_nowait()
```


### 5. Docker volumes (не потерять данные!)

```yaml
# docker-compose.yml
volumes:
  postgres_data:  # Persistence для БД
  tiles_cache:    # Кэш растровых tiles

services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data
  api:
    volumes:
      - tiles_cache:/data/tiles
```


***

## ✅ Готовность к разработке (финальный чеклист)

- [x] Routing Engine: pgRouting (с diversity penalties)
- [x] Graph Storage: PostgreSQL + PostGIS (spatial indexes)
- [x] MVT: On-the-fly generation (pre-computed geom_3857)
- [x] SimulationCore: Memory-first (numpy, batch sync)
- [x] Agent: Физика движения (acceleration/deceleration zones)
- [x] Capacity: Формула (R\&D-1: simple, R\&D-2: realistic)
- [x] Turn penalties: Двухуровневый (cost + agent physics)
- [x] Coordinator: Priority + rerouting strategy
- [x] Тестирование: Baseline vs MAS (сценарии готовы)
- [x] Конфиги: YAML (все параметры настраиваемы)
- [x] Метрики: Prometheus + Grafana (bottleneck detection)

**Архитектура полностью готова!** Можно стартовать разработку с агентом. 🚀

***

**Удачи в реализации!**

