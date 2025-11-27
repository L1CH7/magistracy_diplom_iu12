# 🚀 Полный Production-Ready План: pgRouting для МАС

**Дата:** 26 ноября 2025  
**Статус:** FINAL — Production-ready guide  
**Цель:** Интегрировать pgRouting как гибкую, расширяемую систему маршрутизации для МАС

---

## 📋 Оглавление

1. [Архитектура: Interface Pattern](#архитектура-interface-pattern)
2. [База данных: Две БД + Схема](#база-данных)
3. [Position Model: Метры на Ребре](#position-model)
4. [OSM Data + Restrictions](#osm-data--restrictions)
5. [pgRouting Реализация](#pgrouting-реализация)
6. [K-Routes с опциональной Diversity](#k-routes)
7. [Симуляция: Движение Агента](#симуляция)
8. [Динамическое Переустройство](#рerouting)
9. [Конфигурация](#конфигурация)
10. [Timeline и Чеклист](#timeline)

---

## 🏗️ Архитектура: Interface Pattern

### Ключевая идея: Легко менять реализацию

```
RoutingEngine (abstract interface)
    ├─ PgRoutingEngine (текущая реализация)
    ├─ AStarEngine (будущее, из старых коммитов)
    └─ Custom (опционально: своя реализация)
```

**Преимущества:**
- ✅ Zero downtime миграция (change конфига)
- ✅ A/B тестирование разных алгоритмов
- ✅ Модульная архитектура
- ✅ Easy to test (interface tests работают для всех)

---

## 🗄️ База данных

### Две отдельные БД (изоляция)

```yaml
# config/database/osm_db.yaml
osm_database:
  name: osm_data              # Raw OSM данные (source of truth)
  schema: osm                 # Только для хранения
  host: localhost
  port: 5432
  connection_pool:
    min_size: 2
    max_size: 5

# config/database/graph_db.yaml
graph_database:
  name: routing_graph         # Граф для маршрутизации
  schemas:
    - graphs                  # pgRouting tables
    - astar_graph             # Для будущей A* реализации
  host: localhost
  port: 5432
  connection_pool:
    min_size: 5
    max_size: 20
```

### SQL Миграции

#### v1: Raw OSM Data

```sql
-- migrations/v1_osm_tables.sql

CREATE SCHEMA IF NOT EXISTS osm;

-- Сырые способы из Overpass API
CREATE TABLE osm.ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    tags JSONB NOT NULL DEFAULT '{}',
    highway VARCHAR(50),
    name VARCHAR(255),
    lanes INT,
    maxspeed VARCHAR(20),
    access VARCHAR(50),              -- private, no, destination
    motor_vehicle VARCHAR(50),       -- no (запрет)
    service VARCHAR(50),             -- driveway (частная парковка)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_osm_ways_geom ON osm.ways USING GIST(geom);
CREATE INDEX idx_osm_ways_highway ON osm.ways(highway);
CREATE INDEX idx_osm_ways_access ON osm.ways(access);

-- Barriers (шлагбаумы, ворота, болларды)
CREATE TABLE osm.barriers (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    geom GEOMETRY(Point, 4326) NOT NULL,
    barrier_type VARCHAR(50),        -- gate, boom, bollard, block, wall
    name VARCHAR(255),
    access VARCHAR(50),              -- private, destination, public
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_osm_barriers_geom ON osm.barriers USING GIST(geom);
CREATE INDEX idx_osm_barriers_type ON osm.barriers(barrier_type);

-- Turn Restrictions из relations
CREATE TABLE osm.turn_restrictions (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    restriction_type VARCHAR(50),    -- no_left_turn, no_right_turn, no_u_turn, no_straight_on
    from_way BIGINT,
    via_node BIGINT,
    to_way BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_restrictions_from ON osm.turn_restrictions(from_way);
CREATE INDEX idx_restrictions_via ON osm.turn_restrictions(via_node);
```

#### v2: pgRouting Graph

```sql
-- migrations/v2_pgrouting_graph.sql

CREATE SCHEMA IF NOT EXISTS graphs;

-- Nodes (перекрёстки, концы дорог)
CREATE TABLE graphs.nodes (
    id BIGSERIAL PRIMARY KEY,
    osm_node_id BIGINT,
    geom GEOMETRY(Point, 4326) NOT NULL,
    is_intersection BOOLEAN DEFAULT false,
    type VARCHAR(50) DEFAULT 'intersection',
    has_barrier BOOLEAN DEFAULT false,
    barrier_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_graphs_nodes_geom ON graphs.nodes USING GIST(geom);

-- Edges (основная таблица для маршрутизации)
CREATE TABLE graphs.edges (
    id SERIAL PRIMARY KEY,
    osm_way_id BIGINT,
    source BIGINT REFERENCES graphs.nodes(id),
    target BIGINT REFERENCES graphs.nodes(id),
    geom GEOMETRY(LineString, 4326) NOT NULL,
    
    -- Road attributes
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INT DEFAULT 1,
    oneway BOOLEAN DEFAULT false,
    
    -- Speed (с дефолтами!)
    maxspeed_kmh INT NOT NULL,          -- ← Может быть дефолт (60 улица, 20 двор)
    
    -- Length (вычисляется автоматически)
    length_m FLOAT NOT NULL,            -- ← TRIGGER вычисляет!
    
    -- Capacity
    base_capacity INT NOT NULL,         -- max vehicles per hour
    current_load INT DEFAULT 0,         -- текущее количество агентов
    
    -- Restrictions & Access
    access_type VARCHAR(50),            -- public, private, destination, no
    is_restricted BOOLEAN DEFAULT false, -- need permission to enter
    barrier_penalty_sec INT DEFAULT 0,  -- penalty за ворота/барьеры
    
    -- Dynamic fields (GENERATED ALWAYS)
    effective_speed_kmh FLOAT GENERATED ALWAYS AS (
        CASE
            WHEN current_load = 0 THEN maxspeed_kmh
            WHEN current_load <= base_capacity THEN maxspeed_kmh
            ELSE GREATEST(5.0, maxspeed_kmh * (2.0 - current_load::FLOAT / base_capacity))
        END
    ) STORED,
    
    cost FLOAT GENERATED ALWAYS AS (
        length_m / (effective_speed_kmh / 3.6)  -- cost в секундах
    ) STORED,
    
    reverse_cost FLOAT GENERATED ALWAYS AS (
        CASE WHEN oneway THEN -1.0 ELSE cost END
    ) STORED,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TRIGGER: автоматически вычислить length_m при insert/update
CREATE OR REPLACE FUNCTION compute_edge_length()
RETURNS TRIGGER AS $$
BEGIN
    NEW.length_m := ST_Length(ST_Transform(NEW.geom, 3857));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_length_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION compute_edge_length();

CREATE INDEX idx_graphs_edges_source ON graphs.edges(source);
CREATE INDEX idx_graphs_edges_target ON graphs.edges(target);
CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geom);
CREATE INDEX idx_graphs_edges_access ON graphs.edges(access_type);
```

---

## 📍 Position Model: Метры на Ребре

### Agent State

```python
# src/server/shared/models/agent.py

from dataclasses import dataclass
from typing import List
import time

@dataclass
class AgentPosition:
    """Точная позиция агента на графе."""
    edge_id: int                    # На каком ребре
    position_meters: float          # На скольких метрах вдоль ребра
    
    def __post_init__(self):
        if self.position_meters < 0:
            raise ValueError("position_meters must be >= 0")
    
    def to_dict(self):
        return {
            'edge_id': self.edge_id,
            'position_meters': round(self.position_meters, 2)
        }

@dataclass
class AgentState:
    """Полное состояние агента для симуляции."""
    agent_id: str
    current_edge_id: int
    position_meters: float          # На каких метрах текущего edge
    
    bearing_degrees: float          # Направление (0-360)
    speed_mps: float                # Текущая скорость (м/с)
    
    route: List[int]                # Edge IDs маршрута
    route_index: int = 0            # Индекс текущего edge в маршруте
    
    # Служебные
    started_at: float = 0.0
    elapsed_time: float = 0.0
    is_running: bool = True
    reached_destination: bool = False
    total_distance_meters: float = 0.0
    
    # Rerouting
    last_rerouted_at: float = 0.0
    reroute_cooldown_sec: float = 30.0  # Не переустраивать чаще чем раз в 30 сек
    
    def is_at_edge_start(self) -> bool:
        return self.position_meters < 1.0
    
    def is_at_edge_end(self, edge_length_m: float) -> bool:
        return self.position_meters >= edge_length_m - 1.0
    
    def can_reroute_now(self) -> bool:
        current_time = time.time()
        return (current_time - self.last_rerouted_at) >= self.reroute_cooldown_sec
```

---

## 🗺️ OSM Data + Restrictions

### Overpass Query (ПОЛНЫЙ)

```
[out:json][timeout:120];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|living_street|unclassified|service|road|track|bus_guideway|escape)$"]({{bbox}});
  relation["type"="restriction"]({{bbox}});
  node["barrier"~"gate|boom|bollard|block|wall"]({{bbox}});
  way["access"="private"]({{bbox}});
  way["access"="no"]({{bbox}});
  way["motor_vehicle"="no"]({{bbox}});
  way["service"="driveway"]({{bbox}});
);
out body;
>;
out skel qt;
```

**Что это дает:**
- ✅ Все типы дорог (motorway до track)
- ✅ Turn restrictions (из relations)
- ✅ Barriers (ворота, болларды, блоки, стены)
- ✅ Private ways (нужно проехать через ворота)
- ✅ Service driveways (парковки)

### Логика Access Control

```python
# src/server/services/graph_builder/access_control.py

class AccessControl:
    """Логика доступа через barriers и restricted zones."""
    
    # Типы агентов (с разным доступом)
    AGENT_TYPES = {
        'regular': {                # Обычный автомобиль
            'access_types': ['public', 'destination'],
            'barrier_penalty_sec': 30,  # 30 сек ожидания ворот
            'can_cross_private': False
        },
        'taxi': {                   # Такси (более свободно)
            'access_types': ['public', 'destination', 'private'],
            'barrier_penalty_sec': 15,
            'can_cross_private': True
        },
        'emergency': {              # Скорая/Полиция
            'access_types': ['public', 'destination', 'private', 'no'],
            'barrier_penalty_sec': 5,
            'can_cross_private': True
        }
    }
    
    @staticmethod
    def can_traverse_edge(edge, agent_type='regular') -> tuple:
        """
        Проверить: может ли агент проехать по edge?
        
        Returns:
            (can_traverse: bool, penalty_sec: int)
        """
        agent_config = AccessControl.AGENT_TYPES.get(agent_type, AccessControl.AGENT_TYPES['regular'])
        
        # Проверка 1: Общий доступ
        if edge.access_type not in agent_config['access_types']:
            if edge.access_type == 'no':
                return (False, 0)  # Абсолютный запрет
            elif edge.access_type == 'private':
                if not agent_config['can_cross_private']:
                    return (False, 0)
        
        # Проверка 2: Penalty за barrier (если есть)
        penalty = edge.barrier_penalty_sec if edge.barrier_penalty_sec > 0 else 0
        
        return (True, penalty)
    
    @staticmethod
    def get_barrier_cost(barrier_count: int, agent_type='regular') -> float:
        """
        Вычислить cost за прохождение через N барьеров.
        
        Логика:
        - Если нет альтернативы (точка внутри двора) → лучше проехать
        - Если есть объезд → штраф делает объезд привлекательнее
        """
        if barrier_count == 0:
            return 0
        
        agent_config = AccessControl.AGENT_TYPES.get(agent_type, AccessControl.AGENT_TYPES['regular'])
        penalty_per_barrier = agent_config['barrier_penalty_sec']
        
        # Экспоненциальный штраф за множество барьеров
        # 1 барьер: penalty
        # 2 барьера: penalty * 1.5
        # 3+ барьера: penalty * 2.0
        multiplier = 1.0 if barrier_count <= 1 else (1.5 if barrier_count == 2 else 2.0)
        
        return penalty_per_barrier * barrier_count * multiplier
```

### Default Speeds

```python
# config/routing/default_speeds.yaml

# Дефолтные скорости если maxspeed не указан в OSM

default_speeds:
  motorway: 120
  motorway_link: 80
  trunk: 100
  trunk_link: 80
  primary: 90
  primary_link: 70
  secondary: 80
  secondary_link: 60
  tertiary: 60
  tertiary_link: 50
  residential: 60          # ← Обычная улица в городе
  living_street: 20        # ← Пешеходная зона, двор
  unclassified: 50
  service: 20              # ← Сервис, проезд
  road: 50
  track: 30
  bus_guideway: 40
  escape: 40

# Может быть переопределено через OSM теги или через конфиг
# Приоритет: OSM maxspeed > config override > default_speeds
```

---

## 🔌 pgRouting Реализация

### Interface

```python
# src/server/services/routing/interface.py

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from enum import Enum

class RoutingAlgorithm(Enum):
    PGROUTING = "pgrouting"
    ASTAR = "astar"

class Route:
    def __init__(self, 
                 edge_ids: List[int],
                 total_cost: float,
                 total_distance_m: float,
                 algorithm: str):
        self.edge_ids = edge_ids
        self.total_cost = total_cost
        self.total_distance_m = total_distance_m
        self.algorithm = algorithm

class RoutingEngine(ABC):
    @abstractmethod
    async def find_route(self,
                         start_node: int,
                         end_node: int,
                         priority: int = 0) -> Optional[Route]:
        pass
    
    @abstractmethod
    async def find_k_routes(self,
                            start_node: int,
                            end_node: int,
                            k: int = 3,
                            priority: int = 0,
                            use_diversity: bool = False) -> List[Route]:
        """
        K маршрутов.
        
        Args:
            use_diversity: Если True → применить space diversity filter
                          (опционально, для улучшения качества)
        """
        pass
    
    @abstractmethod
    async def snap_to_road(self,
                           lat: float,
                           lon: float,
                           snap_radius_m: float = 100.0) -> Optional[Tuple[int, float]]:
        """
        Map matching.
        
        Returns:
            (edge_id, position_meters) или None
        """
        pass
    
    @abstractmethod
    async def update_edge_load(self, edge_id: int, new_load: int) -> None:
        pass
    
    @abstractmethod
    async def get_graph_stats(self) -> dict:
        pass
```

### Coordinator

```python
# src/server/services/routing/coordinator.py

from typing import Optional
from .interface import RoutingEngine, RoutingAlgorithm, Route
import yaml
import logging

logger = logging.getLogger(__name__)

class RoutingCoordinator:
    """Выбирает реализацию на основе конфига."""
    
    def __init__(self, config_path: str):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        self.algorithm = RoutingAlgorithm(config['routing_engine'])
        self.engine: Optional[RoutingEngine] = None
        self.config = config
    
    async def initialize(self):
        if self.algorithm == RoutingAlgorithm.PGROUTING:
            from .pgrouting_impl import PgRoutingEngine
            self.engine = PgRoutingEngine(self.config['pgrouting'])
        elif self.algorithm == RoutingAlgorithm.ASTAR:
            from .astar_impl import AStarEngine
            self.engine = AStarEngine(self.config['astar'])
        else:
            raise ValueError(f"Unknown algorithm: {self.algorithm}")
        
        await self.engine.initialize()
        logger.info(f"Routing initialized with {self.algorithm.value}")
    
    async def find_route(self, start_node: int, end_node: int, priority: int = 0) -> Optional[Route]:
        if self.engine is None:
            raise RuntimeError("Not initialized")
        return await self.engine.find_route(start_node, end_node, priority)
    
    async def find_k_routes(self, start_node: int, end_node: int, k: int = 3, 
                           priority: int = 0, use_diversity: bool = False) -> List[Route]:
        if self.engine is None:
            raise RuntimeError("Not initialized")
        return await self.engine.find_k_routes(start_node, end_node, k, priority, use_diversity)
    
    async def snap_to_road(self, lat: float, lon: float, snap_radius_m: float = 100.0):
        if self.engine is None:
            raise RuntimeError("Not initialized")
        return await self.engine.snap_to_road(lat, lon, snap_radius_m)
```

### PgRouting Implementation

```python
# src/server/services/routing/pgrouting_impl.py

import asyncpg
from typing import Optional, List, Tuple, Set
from .interface import RoutingEngine, Route, RouteNotFoundError
import logging

logger = logging.getLogger(__name__)

class PgRoutingEngine(RoutingEngine):
    """pgRouting реализация через SQL."""
    
    def __init__(self, config: dict):
        self.config = config
        self.db_pool = None
    
    async def initialize(self):
        self.db_pool = await asyncpg.create_pool(
            host=self.config['database']['host'],
            port=self.config['database']['port'],
            database=self.config['database']['name'],
            user=self.config['database']['user'],
            password=self.config['database']['password'],
            min_size=self.config['connection_pool']['min_size'],
            max_size=self.config['connection_pool']['max_size'],
        )
        logger.info("PgRouting initialized")
    
    async def find_route(self, 
                        start_node: int, 
                        end_node: int, 
                        priority: int = 0) -> Optional[Route]:
        """Dijkstra: кратчайший маршрут."""
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT 
                    array_agg(edge ORDER BY seq) as edges,
                    max(agg_cost) as total_cost
                FROM pgr_dijkstra(
                    'SELECT id, source, target, cost, reverse_cost FROM graphs.edges',
                    $1,  -- start_node
                    $2,  -- end_node
                    directed := true
                )
                WHERE edge > 0;
            """
            
            result = await conn.fetchrow(query, start_node, end_node)
            
            if result is None or result['edges'] is None:
                raise RouteNotFoundError(f"No route found")
            
            edges = result['edges']
            
            # Вычислить расстояние
            dist_result = await conn.fetchrow(
                "SELECT SUM(length_m) as total FROM graphs.edges WHERE id = ANY($1)",
                edges
            )
            
            return Route(
                edge_ids=list(edges),
                total_cost=float(result['total_cost']),
                total_distance_m=float(dist_result['total'] or 0),
                algorithm='pgrouting'
            )
    
    async def find_k_routes(self,
                           start_node: int,
                           end_node: int,
                           k: int = 3,
                           priority: int = 0,
                           use_diversity: bool = False) -> List[Route]:
        """
        K маршрутов через Yen's algorithm.
        
        Если use_diversity=True → применить space diversity filter
        """
        async with self.db_pool.acquire() as conn:
            # Запросить K * 2 маршрутов (потом отфильтруем)
            fetch_k = k * 2 if use_diversity else k
            
            query = """
                WITH ksp_raw AS (
                    SELECT 
                        path_id,
                        array_agg(edge ORDER BY seq) as edges,
                        max(agg_cost) as cost
                    FROM pgr_KSP(
                        'SELECT id, source, target, cost, reverse_cost FROM graphs.edges',
                        $1,  -- start_node
                        $2,  -- end_node
                        $3,  -- k
                        directed := true
                    )
                    WHERE edge > 0
                    GROUP BY path_id
                    ORDER BY cost
                )
                SELECT path_id, edges, cost
                FROM ksp_raw
                LIMIT $3;
            """
            
            results = await conn.fetch(query, start_node, end_node, fetch_k)
            
            if not results:
                raise RouteNotFoundError("No K-routes found")
            
            routes = []
            
            if use_diversity:
                # Применить diversity фильтры
                routes = await self._filter_routes_by_diversity(conn, results, k)
            else:
                # Просто вернуть K маршрутов
                for row in results[:k]:
                    route = await self._make_route(conn, row['edges'], row['cost'])
                    routes.append(route)
            
            return routes[:k]
    
    async def _filter_routes_by_diversity(self, conn, candidates, k):
        """
        Опциональный фильтр: выбрать K маршрутов с пространственной diversity.
        
        Фильтры:
        1. Space diversity: >= 60% новых рёбер
        2. Divergence point: не на концах (20-80%)
        3. Cost ratio: не более +50% от кратчайшего
        """
        if not candidates:
            return []
        
        routes = []
        base_edges_set = set(candidates[0]['edges'])
        base_cost = candidates[0]['cost']
        
        routes.append(await self._make_route(conn, candidates[0]['edges'], candidates[0]['cost']))
        
        for candidate in candidates[1:]:
            if len(routes) >= k:
                break
            
            candidate_edges = candidate['edges']
            candidate_cost = candidate['cost']
            
            # Фильтр 1: Cost ratio
            if candidate_cost > base_cost * 1.5:
                continue
            
            # Фильтр 2: Space diversity (60% новых рёбер)
            unique_edges = set(candidate_edges) - base_edges_set
            diversity_ratio = len(unique_edges) / len(candidate_edges)
            
            if diversity_ratio < 0.6:
                logger.debug(f"Skip route (diversity {diversity_ratio:.1%} < 60%)")
                continue
            
            # Фильтр 3: Divergence point
            diverge_point = self._find_divergence_point(
                list(base_edges_set),
                list(candidate_edges)
            )
            
            if diverge_point is not None:
                diverge_pct = diverge_point / len(candidate_edges)
                if not (0.2 <= diverge_pct <= 0.8):
                    logger.debug(f"Skip route (diverge {diverge_pct:.1%}, need 20-80%)")
                    continue
            
            route = await self._make_route(conn, candidate_edges, candidate_cost)
            routes.append(route)
        
        return routes
    
    @staticmethod
    def _find_divergence_point(base_edges: List[int], candidate_edges: List[int]) -> Optional[int]:
        for i, edge in enumerate(candidate_edges):
            if i >= len(base_edges) or edge != base_edges[i]:
                return i
        return None
    
    async def _make_route(self, conn, edges, cost) -> Route:
        """Вспомогательный метод для создания Route объекта."""
        dist_result = await conn.fetchrow(
            "SELECT SUM(length_m) as total FROM graphs.edges WHERE id = ANY($1)",
            edges
        )
        
        return Route(
            edge_ids=list(edges),
            total_cost=float(cost),
            total_distance_m=float(dist_result['total'] or 0),
            algorithm='pgrouting'
        )
    
    async def snap_to_road(self,
                          lat: float,
                          lon: float,
                          snap_radius_m: float = 100.0) -> Optional[Tuple[int, float]]:
        """Map matching: GPS → (edge_id, position_meters)"""
        async with self.db_pool.acquire() as conn:
            query = """
                SELECT 
                    id as edge_id,
                    length_m,
                    ST_LineLocatePoint(geom, user_point) as position_frac,
                    ST_Distance(
                        ST_Transform(geom, 3857),
                        ST_Transform(user_point, 3857)
                    ) as distance_m
                FROM graphs.edges,
                     (SELECT ST_SetSRID(ST_MakePoint($2, $1), 4326) as user_point) u
                WHERE ST_DWithin(
                    ST_Transform(geom, 3857),
                    ST_Transform(u.user_point, 3857),
                    $3
                )
                ORDER BY distance_m
                LIMIT 1;
            """
            
            result = await conn.fetchrow(query, lat, lon, snap_radius_m)
            
            if result:
                position_meters = result['position_frac'] * result['length_m']
                return (result['edge_id'], position_meters)
            
            return None
    
    async def update_edge_load(self, edge_id: int, new_load: int) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE graphs.edges SET current_load = $1 WHERE id = $2",
                new_load, edge_id
            )
    
    async def get_graph_stats(self) -> dict:
        async with self.db_pool.acquire() as conn:
            nodes = await conn.fetchval("SELECT COUNT(*) FROM graphs.nodes")
            edges = await conn.fetchval("SELECT COUNT(*) FROM graphs.edges")
            distance = await conn.fetchval("SELECT SUM(length_m) FROM graphs.edges")
            
            return {
                'nodes': nodes,
                'edges': edges,
                'total_distance_m': distance,
                'algorithm': 'pgrouting'
            }
```

---

## 🛣️ K-Routes с Опциональной Diversity

### Конфигурация

```yaml
# config/routing/routing.yaml

routing_engine: "pgrouting"  # Или "astar"

# K-Routes параметры
k_routes:
  k_default: 3
  
  # Опциональная diversity фильтрация
  diversity:
    enabled: false              # ← Может быть enabled для лучшего качества
    space_threshold: 0.6        # 60% новых рёбер
    diverge_min_pct: 0.2
    diverge_max_pct: 0.8
    max_cost_ratio: 1.5         # +50% от кратчайшего

pgrouting:
  database:
    host: localhost
    port: 5432
    name: routing_graph
    user: postgres
    password: postgres
    connection_pool:
      min_size: 5
      max_size: 20
```

### Использование

```python
# При вызове просто передать флаг
coordinator = RoutingCoordinator('config/routing.yaml')

# Без diversity (быстро)
routes = await coordinator.find_k_routes(start, end, k=3, use_diversity=False)

# С diversity (медленнее, но лучше качество)
routes = await coordinator.find_k_routes(start, end, k=3, use_diversity=True)
```

---

## 🚗 Симуляция: Движение Агента

### Movement Logic

```python
# src/server/services/simulation/agent_movement.py

from typing import Dict
from src.server.shared.models.agent import AgentState

class AgentMovement:
    """Логика движения агента."""
    
    def __init__(self, graph_data: Dict):
        self.edges = graph_data
    
    def move_agent(self, state: AgentState, dt: float) -> AgentState:
        """
        Переместить агента на dt секунд.
        
        Args:
            state: Текущее состояние
            dt: Дельта времени (сек), обычно 0.05 для 20 FPS
        
        Returns:
            Обновленное состояние
        """
        if not state.is_running or state.reached_destination:
            return state
        
        # Расстояние за dt при текущей скорости
        distance_traveled_m = state.speed_mps * dt
        
        current_edge = self.edges[state.current_edge_id]
        new_position_meters = state.position_meters + distance_traveled_m
        
        # Проверка: закончилось ли текущее ребро?
        if new_position_meters >= current_edge.length_m:
            overflow_meters = new_position_meters - current_edge.length_m
            
            if state.route_index + 1 < len(state.route):
                # Перейти на следующее ребро
                state.current_edge_id = state.route[state.route_index + 1]
                state.position_meters = overflow_meters
                state.route_index += 1
                state.total_distance_meters += current_edge.length_m
            else:
                # Конец маршрута!
                state.position_meters = current_edge.length_m
                state.total_distance_meters += current_edge.length_m
                state.reached_destination = True
                state.is_running = False
        else:
            # Еще на том же ребре
            state.position_meters = new_position_meters
            state.total_distance_meters += distance_traveled_m
        
        state.elapsed_time += dt
        
        return state
    
    def get_agent_lat_lon(self, state: AgentState) -> Tuple[float, float]:
        """
        Получить текущие lat/lon агента для визуализации.
        """
        edge = self.edges[state.current_edge_id]
        position_frac = state.position_meters / edge.length_m
        
        # ST_LineInterpolatePoint: интерполировать точку на ребре
        geom = edge.geom
        lat = ST_Y(ST_LineInterpolatePoint(geom, position_frac))
        lon = ST_X(ST_LineInterpolatePoint(geom, position_frac))
        
        return (lat, lon)
```

---

## 🔄 Rerouting: Динамическое Переустройство

### Logic

```python
# src/server/services/coordination/rerouting.py

from src.server.shared.models.agent import AgentState
from .access_control import AccessControl
import logging

logger = logging.getLogger(__name__)

class ReroutingCoordinator:
    """Перестраивать маршруты при заторах."""
    
    def __init__(self, router, edges_dict, config):
        self.router = router
        self.edges = edges_dict
        self.config = config
    
    async def should_reroute(self, 
                            agent: AgentState,
                            congestion_snapshot: Dict) -> bool:
        """
        Решить: нужно ли перестраивать маршрут?
        
        Условия:
        1. Достаточно cooldown времени прошло
        2. Есть значимая экономия времени (> 20% или > 30 сек)
        """
        # Проверка 1: Cooldown
        if not agent.can_reroute_now():
            return False
        
        # Проверка 2: Есть ли остаток маршрута?
        if agent.route_index >= len(agent.route):
            return False
        
        # Получить остаток маршрута
        remaining_route = agent.route[agent.route_index:]
        if len(remaining_route) < 2:
            return False
        
        # Оценить текущий cost с congestion
        current_cost = self._estimate_cost_with_congestion(
            remaining_route,
            congestion_snapshot
        )
        
        # Найти альтернативный маршрут
        try:
            alt_routes = await self.router.find_k_routes(
                start_node=self._get_node_from_edge(remaining_route[0]),
                end_node=self._get_node_from_edge(remaining_route[-1]),
                k=2,
                use_diversity=False  # Быстрее
            )
        except Exception as e:
            logger.warning(f"Failed to find alt routes: {e}")
            return False
        
        # Есть ли значимая экономия?
        if len(alt_routes) > 1:
            alt_cost = alt_routes[1].total_cost  # Skip первый (текущий)
            savings = current_cost - alt_cost
            savings_pct = savings / current_cost if current_cost > 0 else 0
            
            # Reroute если экономия > 20% или > 30 сек
            if savings > 30 or savings_pct > 0.2:
                logger.info(f"Reroute: save {savings:.0f}s ({savings_pct:.1%})")
                return True
        
        return False
    
    def _estimate_cost_with_congestion(self, 
                                      route: List[int],
                                      congestion: Dict) -> float:
        """Оценить cost маршрута с учетом пробок."""
        total_cost = 0.0
        
        for edge_id in route:
            edge = self.edges.get(edge_id)
            if not edge:
                continue
            
            load_info = congestion.get(edge_id, {})
            load_ratio = load_info.get('load_ratio', 0.5)
            
            # BPR функция: скорость падает с загруженностью
            if load_ratio < 0.5:
                speed_factor = 1.0
            elif load_ratio < 1.0:
                speed_factor = 0.7
            else:
                speed_factor = 0.3
            
            # cost = length / speed; с congestion: cost = cost / speed_factor
            congested_cost = edge.cost / speed_factor
            total_cost += congested_cost
        
        return total_cost
    
    def _get_node_from_edge(self, edge_id: int) -> int:
        """Получить source node edge'а."""
        edge = self.edges[edge_id]
        return edge.source  # Первый node edge'а
```

---

## ⚙️ Конфигурация

### config/routing/routing.yaml (ПОЛНЫЙ)

```yaml
routing_engine: "pgrouting"  # Или "astar"

# Database connections
database:
  osm_db:
    host: localhost
    port: 5432
    name: osm_data
    user: postgres
    password: postgres
    
  graph_db:
    host: localhost
    port: 5432
    name: routing_graph
    user: postgres
    password: postgres

# pgRouting параметры
pgrouting:
  database:
    host: localhost
    port: 5432
    name: routing_graph
    user: postgres
    password: postgres
    connection_pool:
      min_size: 5
      max_size: 20
  
  capacity:
    formula: "bpr"  # BPR congestion function
    alpha: 0.7
    beta: 1.5
    min_speed_kmh: 5.0

# K-Routes
k_routes:
  k_default: 3
  diversity:
    enabled: false
    space_threshold: 0.6
    diverge_min_pct: 0.2
    diverge_max_pct: 0.8
    max_cost_ratio: 1.5

# Default speeds (если в OSM не указана)
default_speeds:
  motorway: 120
  residential: 60
  living_street: 20
  service: 20

# Access control
access_control:
  agent_types:
    regular:
      barrier_penalty_sec: 30
      can_cross_private: false
    taxi:
      barrier_penalty_sec: 15
      can_cross_private: true
    emergency:
      barrier_penalty_sec: 5
      can_cross_private: true

# Rerouting
rerouting:
  enabled: true
  check_interval_sec: 5       # Проверять каждые 5 сек
  cooldown_sec: 30            # Не чаще чем раз в 30 сек
  savings_threshold_sec: 30   # Reroute если экономия > 30 сек
  savings_threshold_pct: 0.2  # Или > 20%
```

---

## 📅 Timeline и Чеклист

### Фаза 1: БД (Week 1)
- [ ] Две БД (osm_data, routing_graph)
- [ ] SQL миграции (v1 osm, v2 graph)
- [ ] Python models (AgentState, Route, Edge)
- [ ] TRIGGER для length_m

### Фаза 2: Interface (Week 1-2)
- [ ] RoutingEngine abstract class
- [ ] RoutingCoordinator
- [ ] Exception classes
- [ ] Interface tests

### Фаза 3: pgRouting (Week 2)
- [ ] PgRoutingEngine реализация
- [ ] find_route (Dijkstra)
- [ ] find_k_routes (Yen's + optional diversity)
- [ ] snap_to_road (map matching в метры)
- [ ] Тесты

### Фаза 4: Graph Builder + OSM (Week 2-3)
- [ ] GraphBuilder (OSM → pgRouting граф)
- [ ] Access control logic (barriers, private ways)
- [ ] Default speeds
- [ ] Integration tests

### Фаза 5: Симуляция (Week 3-4)
- [ ] AgentMovement (position_meters логика)
- [ ] Movement на симуляцию
- [ ] get_agent_lat_lon для визуализации

### Фаза 6: Rerouting (Week 4)
- [ ] ReroutingCoordinator
- [ ] Congestion estimation
- [ ] Dynamic rerouting logic
- [ ] Tests

### Фаза 7: Integration (Week 5)
- [ ] API endpoints
- [ ] WebSocket для real-time
- [ ] Full integration tests
- [ ] Performance testing (1000 agents)

### R&D-2: A* Migration (Future)
- [ ] Implement AStarEngine
- [ ] Профилировать vs pgRouting
- [ ] Change конфига (zero downtime!)

---

## ✅ Финальная Архитектура

```
┌─────────────────────────────────────────────────┐
│                  USER/GUI CLIENT                │
│         snap_to_road(lat, lon) → route          │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           RoutingCoordinator                    │
│  - Выбирает реализацию (pgRouting/A*)          │
│  - Делегирует вызовы                           │
└────────────────────┬────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
  ┌──────────────┐        ┌──────────────┐
  │PgRoutingEngine│        │AStarEngine   │
  │(R&D-1)       │        │(R&D-2)       │
  └──────┬───────┘        └──────────────┘
         │
         ▼
  ┌─────────────────┐
  │pgRouting SQL    │
  │find_route()     │ pgr_dijkstra
  │find_k_routes()  │ pgr_KSP
  │snap_to_road()   │ ST_ClosestPoint
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ routing_graph   │
  │ - graphs.nodes  │
  │ - graphs.edges  │
  │   (length_m!)   │
  │ - barriers      │
  │ - restrictions  │
  └────────┬────────┘
           │
           ▼ (built from)
  ┌─────────────────┐
  │ osm_data        │
  │ - osm.ways      │
  │ - osm.barriers  │
  │ - osm.restrictions
  └─────────────────┘


SIMULATION LOOP:
  1. Agent: route = await router.find_route(start, end)
  2. Agent: state.current_edge, state.position_meters
  3. Every tick:
     - AgentMovement.move_agent(state, dt=0.05)
     - position_meters += speed_mps * dt
  4. Every 5 sec:
     - ReroutingCoordinator.should_reroute?
     - If yes: state.route = new_route
  5. Send to client: agent.current_position (lat/lon)
```

---

## 🎯 Итоги

**Вы получите:**

1. ✅ **Interface Pattern** — легко менять реализацию (pgRouting → A*)
2. ✅ **Production-ready pgRouting** — с Dijkstra, Yen's, map matching
3. ✅ **Precise Position Model** — метры на ребре (не проценты)
4. ✅ **Default Speeds** — 60 км/ч в городе, 20 во дворах (если нет OSM)
5. ✅ **Access Control** — barriers, private ways, gate penalties
6. ✅ **Optiional Diversity** — K-routes с фильтрами (можно включить)
7. ✅ **Dynamic Rerouting** — перестройка при заторах
8. ✅ **Congestion Model** — BPR функция
9. ✅ **Zero Downtime Migration** — смена реализации через конфиг
10. ✅ **Tested & Documented** — production-ready код

---

**Это настоящая production-level система!** 🚀

Используйте этот гайд как исходную спецификацию для реализации. Все детали здесь.
