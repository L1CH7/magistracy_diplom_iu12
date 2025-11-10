# MAS Navigation System: Полная архитектура и план реализации

**Документ подготовлен:** 2025-11-09  
**Этап:** R&D-1 (Базовая архитектура и прототип)  
**Фокус:** Multi-Agent System для динамической маршрутизации городского транспорта

---

## 📋 Содержание

1. [Обзор проблемы](#обзор-проблемы)
2. [Архитектура системы](#архитектура-системы)
3. [Компоненты и их ответственность](#компоненты-и-их-ответственность)
4. [Модель графа и данных](#модель-графа-и-данные)
5. [Симуляция: как работает](#симуляция-как-работает)
6. [MAS Координатор: принятие решений](#mas-координатор-принятие-решений)
7. [Гибкость системы: конфигурируемые параметры](#гибкость-системы-конфигурируемые-параметры)
8. [План реализации R&D-1](#план-реализации-rd1)

---

## Обзор проблемы

### Основная проблема

**Централизованные системы навигации** (Google Maps, Яндекс) не учитывают динамически поведение множества водителей. Все получают одинаковые "оптимальные" маршруты → перегрузка одних дорог и простой других.

### Цель работы

Разработать **Multi-Agent System (MAS)** для **динамического распределения маршрутов**, которая минимизирует общую загруженность дорожной сети.

### Пример проблемы

```
Сценарий: 1000 автомобилей с одной целью (A → B)

BASELINE (все на кратчайший путь):
├─ Узкое место e1 (capacity=200): load=198 (99% перегруз!)
├─ Магистраль e2 (capacity=2040): load=2 (0.1% использование!)
├─ Результат: средний пробег = 240 минут ❌

MAS РАСПРЕДЕЛЕНИЕ (по 3 альтернативным маршрутам):
├─ e1 (через маршрут 1): load=70 (35% загрузки)
├─ Альтернативные рёбра: распределённо
├─ Результат: средний проезд = 90 минут ✅ (62% улучшение!)
```

---

## Архитектура системы

### Высокоуровневая архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                    КЛИЕНТ (PyQt5 + MapLibre)                 │
│  ├─ Ввод маршрута (точка A, точка B)                        │
│  ├─ Отображение дорог (по типам, скорость, полосы)         │
│  ├─ Визуализация агентов                                    │
│  └─ Heatmap загруженности (green → yellow → red)            │
└──────────────────────────────────────────────────────────────┘
          ↑ REST API / WebSocket (10 запросов/сек)
          ↓

┌──────────────────────────────────────────────────────────────┐
│                     СЕРВЕР (FastAPI)                         │
│  ├─ /api/osm/load_graph          (загрузка OSM в граф)      │
│  ├─ /api/simulation/start        (запуск симуляции)         │
│  ├─ /api/simulation/state        (получить состояние)       │
│  ├─ /api/routes/calculate        (рассчитать маршрут)       │
│  └─ WebSocket: /ws/simulation    (live-обновления)          │
└──────────────────────────────────────────────────────────────┘
          ↓

┌──────────────────────────────────────────────────────────────┐
│              СИМУЛЯЦИЯ (Дискретные шаги, 1 сек)              │
│  while simulation_running:                                   │
│    1. update_agent_positions()    (переместить агентов)     │
│    2. update_edge_loads()         (пересчитать load)        │
│    3. update_effective_speeds()   (пересчитать скорости)    │
│    4. broadcast_state()           (отправить клиенту)       │
│    5. sleep(1)                                              │
└──────────────────────────────────────────────────────────────┘
          ↓ (каждые 30 шагов)

┌──────────────────────────────────────────────────────────────┐
│            MAS КООРДИНАТОР (Принятие решений)                 │
│  if step % 30 == 0:                                         │
│    1. analyze_congestion()                                  │
│    2. identify_bottlenecks()                                │
│    3. calculate_alternative_routes()                        │
│    4. distribute_new_agents()                               │
└──────────────────────────────────────────────────────────────┘
          ↓

┌──────────────────────────────────────────────────────────────┐
│            ROUTING ENGINE (Поиск маршрутов)                   │
│  ├─ A* алгоритм                                             │
│  ├─ Динамические веса (с учётом загруженности)             │
│  └─ K-shortest paths (альтернативные маршруты)            │
└──────────────────────────────────────────────────────────────┘
          ↓

┌──────────────────────────────────────────────────────────────┐
│            GRAPH DATABASE (PostGIS / SQLite)                  │
│  ├─ Nodes (перекрёстки)                                     │
│  ├─ Edges (дороги с атрибутами)                             │
│  └─ Indices для быстрого доступа                            │
└──────────────────────────────────────────────────────────────┘
```

---

## Компоненты и их ответственность

### 1. CLIENT (PyQt5 + MapLibre)

**Текущее состояние:**
- ✅ Ввод маршрута (точки на карте)
- ✅ Загрузка и отображение OSM графа
- ✅ Категоризация дорог (по speed, lanes)

**TODO для R&D-1:**
- [ ] Подключение к серверу (REST API)
- [ ] Live-обновление позиций агентов (WebSocket)
- [ ] Heatmap загруженности (цвет ребра = load/capacity)
- [ ] Контроли для запуска/паузы симуляции
- [ ] Статистика (avg_time, max_load, throughput)

**Ответственность:**
- ✅ Визуализация ТОЛЬКО
- ✅ Ноль логики симуляции
- ✅ Ноль расчётов маршрутов
- ✅ Ноль интеллекта

**Сложность:** Легко (чтение данных + отрисовка)

---

### 2. SERVER (FastAPI)

**Текущее состояние:**
- ✅ Загрузка/отдача OSM tiles
- ✅ Хранение графа в БД
- ⚠️ Кеширование минимальное

**TODO для R&D-1:**
- [ ] REST API для управления симуляцией
- [ ] WebSocket для live-передачи состояния
- [ ] Инициализация симулятора
- [ ] Управление процессом симуляции (start/pause/reset)
- [ ] Сбор метрик и их отправка клиенту

**Ответственность:**
- ✅ Orchestration всех компонентов
- ✅ REST/WebSocket endpoints
- ✅ Управление жизненным циклом симуляции
- ✅ Broadcast состояния клиентам

**Архитектура:**
```python
# server/main.py
app = FastAPI()

@app.post("/api/simulation/start")
async def start_simulation(config: SimulationConfig):
    # Запустить Simulator в отдельном потоке
    simulator = Simulator(config)
    asyncio.create_task(simulator.run())
    return {"status": "started"}

@app.websocket("/ws/simulation")
async def websocket_endpoint(websocket: WebSocket):
    # Broadcast состояния в реальном времени
    while True:
        state = simulator.get_state()
        await websocket.send_json(state)
        await asyncio.sleep(1)
```

---

### 3. SIMULATOR (Ядро физики)

**Текущее состояние:**
- ❌ Не реализовано

**TODO для R&D-1:**
- [ ] Инициализация агентов с маршрутами
- [ ] Дискретная симуляция (шаг = 1 сек)
- [ ] Обновление позиций агентов
- [ ] Обновление load на рёбрах
- [ ] Пересчёт effective_speed
- [ ] Управление жизненным циклом агентов (arrival, removal)

**Ответственность:**
- ✅ Только физика движения
- ✅ Обновление динамических параметров
- ✅ Нет логики маршрутизации
- ✅ Нет интеллекта

**Ключевой цикл:**
```python
# simulator/core/simulation.py
class Simulator:
    def step(self):
        # 1. Обновить load на каждом ребре
        for edge in self.graph.edges:
            edge.current_load = count_agents_on_edge(edge)
        
        # 2. Пересчитать effective_speed
        for edge in self.graph.edges:
            edge.update_effective_speed()  # <-- КОНФИГУРИРУЕМО!
        
        # 3. Переместить агентов
        for agent in self.agents:
            if not agent.arrived:
                agent.move()  # Зависит от edge.effective_speed
        
        # 4. Проверить arrivals
        for agent in self.agents:
            if agent.reached_destination():
                self.metrics.record_arrival(agent)
                agent.arrived = True
        
        # 5. Увеличить time
        self.time += 1
```

**Производительность:**
- Python + NumPy: 5-10 шагов/сек для 1000 агентов
- На R&D-2: можно оптимизировать на C++

---

### 4. MAS COORDINATOR (Интеллект системы)

**Текущее состояние:**
- ❌ Не реализовано (только заглушка)

**TODO для R&D-1:**
- [ ] Анализ congestion на рёбрах
- [ ] Выявление bottlenecks (load > 80% capacity)
- [ ] Распределение новых агентов по маршрутам
- [ ] Интерфейс для подключения RL в R&D-2

**Ответственность:**
- ✅ Принятие решений о распределении маршрутов
- ✅ Анализ текущего состояния сети
- ✅ Нет изменения маршрутов уже движущихся агентов (в R&D-1)
- ✅ Работает независимо от Симулятора

**Архитектура:**
```python
# coordinator/base_coordinator.py
class Coordinator(ABC):
    @abstractmethod
    def distribute_agents(self, new_agents, graph, routing_engine):
        """Распределить новых агентов по маршрутам"""
        pass

# coordinator/simple_coordinator.py (R&D-1)
class SimpleCoordinator(Coordinator):
    def distribute_agents(self, new_agents, graph, routing_engine):
        """Распределение v1: анализ congestion"""
        
        # Анализируем congestion
        congestions = {
            edge.id: edge.current_load / edge.capacity
            for edge in graph.edges
        }
        
        # Выявляем bottlenecks
        bottlenecks = [
            e_id for e_id, cong in congestions.items() if cong > 0.8
        ]
        
        # Распределяем новых агентов
        for agent in new_agents:
            # Получаем K альтернативных маршрутов
            routes = routing_engine.get_k_routes(
                start=agent.start,
                dest=agent.destination,
                k=3,
                avoid_edges=bottlenecks  # Избегаем перегруза
            )
            
            # Выбираем маршрут с наименьшей очередной загруженностью
            best_route = min(
                routes,
                key=lambda r: sum(
                    congestions.get(edge_id, 0) for edge_id in r
                )
            )
            
            agent.route = best_route

# coordinator/rl_coordinator.py (R&D-2)
class RLCoordinator(Coordinator):
    def __init__(self, rl_model):
        self.rl_model = rl_model
    
    def distribute_agents(self, new_agents, graph, routing_engine):
        """Распределение v2: обученная RL модель"""
        
        # State: текущее состояние сети
        state = self.encode_state(graph, new_agents)
        
        # Action: предсказанное распределение
        distribution = self.rl_model.predict(state)
        
        # Применяем распределение
        for agent, route_idx in zip(new_agents, distribution):
            routes = routing_engine.get_k_routes(
                agent.start, agent.destination, k=3
            )
            agent.route = routes[route_idx]
```

**Взаимодействие с Симулятором:**
```python
# В главном цикле сервера
while simulation_running:
    # Каждый шаг симуляции
    simulator.step()
    
    # Каждые 30 шагов: координация
    if simulator.time % 30 == 0:
        new_agents = get_new_agents()
        coordinator.distribute_agents(
            new_agents,
            simulator.graph,
            routing_engine
        )
```

---

### 5. ROUTING ENGINE (Поиск маршрутов)

**Текущее состояние:**
- ❌ Не реализовано

**TODO для R&D-1:**
- [ ] A* алгоритм с динамическими весами
- [ ] K-shortest paths (альтернативные маршруты)
- [ ] Поддержка `avoid_edges` (для обхода bottlenecks)
- [ ] Быстрый доступ к соседним узлам (индексирование)

**Ответственность:**
- ✅ Вычисление оптимальных маршрутов
- ✅ Учёт динамических весов (загруженность)
- ✅ Нет выбора маршрута (это делает Координатор)

**Архитектура:**
```python
# routing/routing_engine.py (интерфейс)
class RoutingEngine(ABC):
    @abstractmethod
    def get_k_routes(self, start, dest, k, avoid_edges=None):
        """Получить K альтернативных маршрутов"""
        pass

# routing/dijkstra_engine.py (реализация)
class DijkstraEngine(RoutingEngine):
    def get_k_routes(self, start, dest, k=3, avoid_edges=None):
        avoid_edges = avoid_edges or []
        routes = []
        
        for _ in range(k):
            # Рассчитываем маршрут с текущими весами
            route = self._dijkstra_with_weights(
                start, dest, avoid_edges
            )
            routes.append(route)
            
            # Увеличиваем вес рёбер в найденном маршруте
            # (чтобы следующий маршрут был другой)
            for edge_id in route:
                self.graph.edges[edge_id].weight_multiplier += 0.5
        
        return routes
    
    def _dijkstra_with_weights(self, start, dest, avoid_edges):
        # Стандартный Dijkstra с динамическими весами
        # weight = base_time * (1 - congestion_factor)
        pass
```

---

### 6. GRAPH DATABASE (PostGIS / SQLite)

**Текущее состояние:**
- ⚠️ Загруженные данные, но не оптимальная структура

**TODO для R&D-1:**
- [ ] Оптимизировать schema для быстрого доступа
- [ ] Индексы на geometry для пространственных запросов
- [ ] Кэширование соседних узлов (adjacency list в памяти)
- [ ] Быстрое получение current_load (запрос за O(1))

**Schema (оптимальная):**
```sql
-- Узлы
CREATE TABLE nodes (
    id SERIAL PRIMARY KEY,
    lat FLOAT,
    lon FLOAT,
    geometry GEOMETRY(POINT, 4326)
);

-- Рёбра (главная таблица)
CREATE TABLE edges (
    id SERIAL PRIMARY KEY,
    start_node_id INT REFERENCES nodes(id),
    end_node_id INT REFERENCES nodes(id),
    
    -- === СТАТИЧЕСКИЕ АТРИБУТЫ (не меняются) ===
    geometry GEOMETRY(LINESTRING, 4326),
    length_m FLOAT,
    speed_limit_kmh FLOAT,
    lanes INT,
    oneway BOOLEAN,
    highway_type VARCHAR(50),  -- "motorway", "trunk", "primary", etc.
    
    -- === ВЫЧИСЛЯЕМЫЕ (один раз) ===
    capacity INT GENERATED AS (CAST(length_m / 5.0 AS INT) * lanes),
    base_travel_time_sec FLOAT GENERATED AS (length_m / (speed_limit_kmh / 3.6)),
    
    -- === ДИНАМИЧЕСКИЕ (обновляются при симуляции) ===
    current_load INT DEFAULT 0,
    last_updated TIMESTAMP
);

-- Индексы для быстрого доступа
CREATE INDEX idx_edges_start_node ON edges(start_node_id);
CREATE INDEX idx_edges_end_node ON edges(end_node_id);
CREATE INDEX idx_edges_geometry ON edges USING GIST(geometry);
```

**В памяти (для быстроты):**
```python
# Загружаем весь граф в память на старте
class Graph:
    def __init__(self, db):
        self.edges = {}
        self.nodes = {}
        self.adjacency_list = defaultdict(list)  # node_id → [edge_ids]
        
        # Загружаем из БД
        for edge in db.query("SELECT * FROM edges"):
            self.edges[edge.id] = Edge(edge)
            self.adjacency_list[edge.start_node_id].append(edge.id)
            self.adjacency_list[edge.end_node_id].append(edge.id)
```

---

## Модель графа и данные

### Структура маршрута (Route)

```
Маршрут A → B = [e1, e2, e3, e4]

Где:
- e1: узкая дорога (2 полосы, 60 км/ч)
- e2: магистраль (10 полос, 100 км/ч)
- e3: средняя дорога (6 полос, 80 км/ч)
- e4: узкая дорога (2 полосы, 60 км/ч)

Каждое ребро имеет:
├─ length_m: 5000, 51000, 29000, 5000 (м)
├─ speed_limit_kmh: 60, 100, 80, 60 (км/ч)
├─ lanes: 2, 10, 6, 2
├─ capacity: 200, 2040, 1164, 200 (агентов одновременно)
└─ current_load: 0-capacity (обновляется каждый шаг)
```

### Движение агента

```
Агент движется дискретно (шаг = 1 сек):

Начало маршрута:
├─ agent.current_edge = e1
├─ agent.position_on_edge = 0.0 (начало ребра)
├─ agent.route = [e2, e3, e4] (остаток маршрута)

Шаг 1 сек:
├─ e1.effective_speed = 58 км/ч = 16.1 м/с
├─ agent.position_on_edge = 0.0 + 16.1 / 5000 = 0.0032 (0.32%)

Шаг 310 сек (~5 минут):
├─ agent.position_on_edge ≈ 1.0 (достиг конца ребра)
├─ Переход: agent.current_edge = e2, agent.position_on_edge = 0.0
├─ agent.route = [e3, e4]

Конец маршрута:
├─ agent.arrived = True
├─ Удаляются из симуляции, записываются метрики
```

---

## Симуляция: как работает

### Дискретная симуляция (временной шаг = 1 сек)

```python
# simulator/core/simulation.py

class Simulator:
    def __init__(self, graph, agents, coordinator):
        self.graph = graph
        self.agents = agents
        self.coordinator = coordinator
        self.time = 0
        self.metrics = Metrics()
    
    def step(self):
        """Один дискретный шаг симуляции (1 сек)"""
        
        # 1️⃣ ОБНОВИТЬ LOAD НА КАЖДОМ РЕБРЕ
        self.update_loads()
        
        # 2️⃣ ПЕРЕСЧИТАТЬ ЭФФЕКТИВНЫЕ СКОРОСТИ
        self.update_speeds()
        
        # 3️⃣ ПЕРЕМЕСТИТЬ АГЕНТОВ
        self.move_agents()
        
        # 4️⃣ УПРАВЛЕНИЕ ЖИЗНЕННЫМ ЦИКЛОМ АГЕНТОВ
        self.handle_arrivals()
        
        # 5️⃣ КАЖДЫЕ 30 ШАГ: КООРДИНАЦИЯ
        if self.time % 30 == 0:
            new_agents = self.generate_agents()
            self.coordinator.distribute_agents(
                new_agents, self.graph, self.routing_engine
            )
        
        self.time += 1
    
    def update_loads(self):
        """Обновить количество агентов на каждом ребре"""
        for edge in self.graph.edges.values():
            edge.current_load = 0
        
        for agent in self.agents:
            if not agent.arrived:
                self.graph.edges[agent.current_edge].current_load += 1
    
    def update_speeds(self):
        """Пересчитать эффективные скорости на рёбрах"""
        for edge in self.graph.edges.values():
            # === КОНФИГУРИРУЕМО! ===
            edge.update_effective_speed()
    
    def move_agents(self):
        """Переместить каждого агента"""
        for agent in self.agents:
            if agent.arrived:
                continue
            
            edge = self.graph.edges[agent.current_edge]
            speed = edge.effective_speed  # м/с
            dt = 1.0  # секунда
            
            distance = speed * dt  # метры
            agent.position_on_edge += distance / edge.length_m
            
            # Проверить достижение конца ребра
            if agent.position_on_edge >= 1.0:
                agent.position_on_edge = 0.0
                
                if len(agent.route) > 0:
                    agent.current_edge = agent.route.pop(0)
                else:
                    agent.arrived = True
    
    def handle_arrivals(self):
        """Записать метрики прибывших агентов"""
        for agent in self.agents:
            if agent.arrived and not agent.recorded:
                travel_time = self.time - agent.start_time
                self.metrics.record_arrival(
                    agent_id=agent.id,
                    travel_time=travel_time,
                    distance=agent.total_distance
                )
                agent.recorded = True
    
    def run(self, duration_sec):
        """Запустить симуляцию на duration_sec секунд"""
        while self.time < duration_sec:
            self.step()
            # Отправить состояние клиенту (1 раз в секунду)
            yield self.get_state()
    
    def get_state(self):
        """Получить текущее состояние для отправки клиенту"""
        return {
            "time": self.time,
            "agents": [
                {
                    "id": a.id,
                    "lat": a.get_latitude(),
                    "lon": a.get_longitude(),
                    "speed": self.graph.edges[a.current_edge].effective_speed
                }
                for a in self.agents if not a.arrived
            ],
            "edge_loads": {
                e_id: {"load": e.current_load, "capacity": e.capacity}
                for e_id, e in self.graph.edges.items()
            },
            "metrics": self.metrics.get_summary()
        }
```

### Пример симуляции: 100 агентов, 1 маршрут

```
TIME | e1_load | e1_congestion | e1_speed | e2_load | e2_speed | AVG_TIME | STATUS
-----|---------|----------------|----------|---------|----------|----------|--------
0min | 5       | 2.5%           | 59 км/ч  | 2       | 100 км/ч | 62 мин   | ✅ OK
2min | 18      | 9%             | 54 км/ч  | 8       | 99.8 км/ч| 66 мин   | ⚠️ e1 загружается
4min | 32      | 16%            | 45 км/ч  | 18      | 99.2 км/ч| 72 мин   | ⚠️ Затор на e1
6min | 42      | 21%            | 37 км/ч  | 32      | 98.4 км/ч| 80 мин   | 🟡 Пробка
8min | 48      | 24%            | 33 км/ч  | 42      | 97.9 км/ч| 87 мин   | 🔴 ЗАТОР
10min| 52      | 26%            | 29 км/ч  | 48      | 97.7 км/ч| 92 мин   | 🔴 ПОЛНАЯ ПРОБКА
```

---

## MAS Координатор: принятие решений

### Разграничение: Симуляция vs MAS

```
СИМУЛЯЦИЯ (физика):
└─ "Где сейчас агент?"
└─ "С какой скоростью он едет?"
└─ "Какой load на каждом ребре?"

MAS (интеллект):
└─ "Какой маршрут выбрать новому агенту?"
└─ "Какие рёбра перегружены?"
└─ "Как распределить агентов чтобы избежать затора?"
```

### Независимость компонентов

```
Симуляция работает НЕЗАВИСИМО:
- Каждый шаг: обновляет позиции, load, скорости
- Не заботится о маршрутах уже движущихся агентов

MAS работает НЕЗАВИСИМО:
- Каждые 30 шагов: анализирует состояние
- Распределяет НОВЫХ агентов (не движущихся)
- Выдаёт маршруты через интерфейс

Взаимодействие:
├─ Симулятор выдаёт: state (positions, loads)
├─ MAS смотрит: state
├─ MAS выдаёт: routes для новых агентов
└─ Симулятор назначает: routes агентам
```

### Архитектура Координатора

```python
# coordinator/base_coordinator.py

from abc import ABC, abstractmethod

class Coordinator(ABC):
    """Абстрактный базовый класс для координаторов"""
    
    @abstractmethod
    def distribute_agents(self, new_agents, graph, routing_engine):
        """
        Распределить новых агентов по маршрутам.
        
        Args:
            new_agents: список новых агентов без маршрутов
            graph: граф дорог с текущим состоянием (load, speed)
            routing_engine: объект для поиска маршрутов
        
        Модифицирует:
            Каждому agent в new_agents назначается agent.route
        """
        pass
    
    def analyze_congestion(self, graph):
        """Анализировать загруженность сети"""
        return {
            edge.id: edge.current_load / edge.capacity
            for edge in graph.edges.values()
        }
    
    def identify_bottlenecks(self, congestion, threshold=0.8):
        """Выявить узкие места (bottlenecks)"""
        return [
            e_id for e_id, cong in congestion.items()
            if cong > threshold
        ]


# coordinator/simple_coordinator.py (R&D-1)

class SimpleCoordinator(Coordinator):
    """
    Простой координатор для R&D-1.
    
    Стратегия:
    1. Анализирует congestion на рёбрах
    2. Выявляет bottlenecks (load > 80% capacity)
    3. Для новых агентов:
       - Получает 3 альтернативных маршрута
       - Выбирает маршрут с наименьшей очередной загруженностью
    """
    
    def distribute_agents(self, new_agents, graph, routing_engine, k=3):
        # Анализируем congestion
        congestion = self.analyze_congestion(graph)
        bottlenecks = self.identify_bottlenecks(congestion, threshold=0.8)
        
        # Распределяем новых агентов
        for agent in new_agents:
            # Получаем K альтернативных маршрутов
            routes = routing_engine.get_k_routes(
                start=agent.start,
                dest=agent.destination,
                k=k,
                avoid_edges=bottlenecks
            )
            
            # Выбираем маршрут с наименьшей очередной загруженностью
            best_route = self._select_best_route(routes, graph)
            agent.route = best_route
    
    def _select_best_route(self, routes, graph):
        """Выбрать маршрут с наименьшей суммарной загруженностью"""
        def route_cost(route):
            return sum(
                graph.edges[edge_id].current_load / graph.edges[edge_id].capacity
                for edge_id in route
            )
        
        return min(routes, key=route_cost)


# coordinator/rl_coordinator.py (R&D-2)

class RLCoordinator(Coordinator):
    """
    Продвинутый RL-координатор для R&D-2.
    
    Использует обученную нейронную сеть для принятия решений.
    Будет реализовано на R&D-2.
    """
    
    def __init__(self, rl_model):
        self.rl_model = rl_model
    
    def distribute_agents(self, new_agents, graph, routing_engine, k=3):
        # State: закодированное состояние сети
        state = self.encode_state(graph, new_agents)
        
        # Action: предсказание RL модели
        distribution = self.rl_model.predict(state)
        
        # Применяем распределение
        for agent, route_idx in zip(new_agents, distribution):
            routes = routing_engine.get_k_routes(
                agent.start, agent.destination, k=k
            )
            agent.route = routes[route_idx % len(routes)]
    
    def encode_state(self, graph, new_agents):
        """Закодировать состояние в вектор для RL"""
        # Будет реализовано на R&D-2
        pass
```

---

## Гибкость системы: конфигурируемые параметры

### Ключевые параметры, которые ДОЛЖНЫ быть конфигурируемы

#### 1. Формула эффективной скорости (CRITICAL!)

```python
# Текущая реализация (упрощённая):
effective_speed = speed_limit * (1 - 0.7 * congestion ** 1.5)

# Компоненты которые должны быть параметризованы:
# - 0.7: "коэффициент влияния загруженности" (alpha)
# - 1.5: "степень нелинейности" (beta)

# Конфигурируемо в config.yaml:
speed_model:
    type: "polynomial"  # или "linear", "exponential", "idelm" и т.д.
    alpha: 0.7           # влияние загруженности
    beta: 1.5            # степень нелинейности
    min_speed_ratio: 0.1 # минимальная скорость = 10% от лимита
```

#### 2. Параметры Координатора

```yaml
coordinator:
    type: "simple"  # или "rl" на R&D-2
    update_interval_sec: 30  # каждые 30 сек пересчитываем
    congestion_threshold: 0.8  # bottleneck если load > 80%
    k_routes: 3  # рассчитываем 3 альтернативных маршрута
    route_selection: "min_cost"  # как выбрать лучший маршрут
```

#### 3. Параметры Симуляции

```yaml
simulation:
    time_step_sec: 1.0  # временной шаг 1 сек
    duration_sec: 3600  # 1 час симуляции
    agents_per_sec: 10  # 10 новых агентов в секунду
    start_point: [55.7522, 37.6156]  # координаты начала
    dest_point: [55.7533, 37.6178]   # координаты конца
```

#### 4. Параметры Графа

```yaml
graph:
    capacity_model: "lanes_based"  # capacity = length/5 * lanes
    # Или: capacity = length/6 * lanes (разные модели авто)
    base_speed_override: {}  # можно переопределить speed_limit для рёбер
    obstacle_multiplier: 1.5  # штраф за перегруз на ребре
```

### Архитектура конфигурации

```python
# config/models.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class SpeedModel:
    """Модель эффективной скорости"""
    type: Literal["polynomial", "linear", "exponential"]
    alpha: float = 0.7  # коэффициент влияния
    beta: float = 1.5   # степень нелинейности
    min_speed_ratio: float = 0.1
    
    def calculate(self, speed_limit, congestion):
        if self.type == "polynomial":
            return speed_limit * (1 - self.alpha * (congestion ** self.beta))
        elif self.type == "linear":
            return speed_limit * (1 - self.alpha * congestion)
        elif self.type == "exponential":
            return speed_limit * (1 - self.alpha) ** (congestion * self.beta)
        
        return max(speed_limit * self.min_speed_ratio, result)


@dataclass
class CoordinatorConfig:
    """Конфигурация Координатора"""
    type: Literal["simple", "rl"]
    update_interval_sec: int = 30
    congestion_threshold: float = 0.8
    k_routes: int = 3


@dataclass
class SimulationConfig:
    """Конфигурация Симуляции"""
    time_step_sec: float = 1.0
    duration_sec: int = 3600
    agents_per_sec: int = 10
    speed_model: SpeedModel
    coordinator: CoordinatorConfig


# config/loader.py

class ConfigLoader:
    @staticmethod
    def from_yaml(filepath: str) -> SimulationConfig:
        import yaml
        with open(filepath) as f:
            data = yaml.safe_load(f)
        
        return SimulationConfig(
            time_step_sec=data["simulation"]["time_step_sec"],
            duration_sec=data["simulation"]["duration_sec"],
            agents_per_sec=data["simulation"]["agents_per_sec"],
            speed_model=SpeedModel(**data["speed_model"]),
            coordinator=CoordinatorConfig(**data["coordinator"])
        )
```

### Использование конфигурации

```python
# main.py или server/main.py

from config.loader import ConfigLoader
from simulator.core.simulation import Simulator

# Загружаем конфиг
config = ConfigLoader.from_yaml("config/simulation.yaml")

# Инициализируем Симулятор с конфигом
simulator = Simulator(
    graph=graph,
    agents=[],
    config=config
)

# Каждый шаг использует параметры из конфига
def step():
    edge.update_effective_speed(config.speed_model)
    coordinator.distribute_agents(..., threshold=config.coordinator.congestion_threshold)
```

---

## План реализации R&D-1

### Текущее состояние (✅ Done)

- ✅ PyQt5 + MapLibre UI
- ✅ Загрузка OSM данных
- ✅ Отображение графа (по типам дорог)
- ✅ Ввод маршрута (точки на карте)

### Этап 1: Подготовка инфраструктуры (Неделя 1)

**Цель:** Готовая сетевая инфраструктура

- [ ] FastAPI сервер с REST endpoints
- [ ] WebSocket для live-передачи
- [ ] PostgreSQL schema для хранения граф + текущего состояния
- [ ] Загрузка графа из БД в память
- [ ] Конфигурация (config.yaml, ConfigLoader)

**Deliverables:**
- `server/main.py` — FastAPI приложение
- `server/routes.py` — REST endpoints
- `database/schema.sql` — SQL schema
- `config/models.py` + `config/simulation.yaml` — конфигурация

---

### Этап 2: Ядро Симуляции (Неделя 1-2)

**Цель:** Работающая симуляция движения агентов

- [ ] `simulator/core/graph.py` — инициализация графа
- [ ] `simulator/core/agent.py` — модель агента
- [ ] `simulator/core/edge.py` — модель ребра с speed_model
- [ ] `simulator/core/simulation.py` — дискретная симуляция
- [ ] `simulator/metrics.py` — сбор метрик (avg_time, max_load, throughput)

**Ключевой цикл:**
```python
while simulation_running:
    simulator.step()  # обновляет load, speed, позиции
    simulator.broadcast_state()  # отправляет клиенту
    sleep(0.1)  # можем ускорить симуляцию 10x vs реального времени
```

**Тесты:**
- [ ] Один агент проезжает маршрут без пробок
- [ ] 100 агентов → congestion на узком месте
- [ ] Метрики считаются правильно

---

### Этап 3: Маршрутизация (Неделя 2)

**Цель:** Поиск маршрутов с динамическими весами

- [ ] `routing/routing_engine.py` — интерфейс
- [ ] `routing/dijkstra_engine.py` — A* с конфигурируемыми весами
- [ ] `routing/utils.py` — вспомогательные функции (KNN соседей, shortest path)

**Функциональность:**
- `get_k_routes(start, dest, k=3)` — K альтернативных маршрутов
- Динамические веса: `weight = base_time * (1 - 0.7 * congestion ** 1.5)`
- Поддержка `avoid_edges` для обхода bottlenecks

**Тесты:**
- [ ] Получить маршрут между двумя узлами
- [ ] Получить 3 альтернативных маршрута
- [ ] Маршруты разные и достаточно хорошие

---

### Этап 4: Координатор (Неделя 2-3)

**Цель:** Распределение агентов по маршрутам

- [ ] `coordinator/base_coordinator.py` — интерфейс
- [ ] `coordinator/simple_coordinator.py` — простой координатор
- Интеграция с Симулятором

**Логика:**
```python
every 30 seconds:
    analyze congestion on all edges
    if max_congestion > 80%:
        identify bottlenecks
        for new_agent:
            get 3 alternative routes (avoiding bottlenecks)
            select route with min total congestion
            assign route to agent
```

**Эксперименты:**
- [ ] Baseline: все агенты на кратчайший путь → ЗАТОР
- [ ] Smart: распределение по 3 маршрутам → меньше затора
- [ ] Таблица результатов (avg_time baseline vs smart)

---

### Этап 5: Интеграция и визуализация (Неделя 3)

**Цель:** Работающая end-to-end система

- [ ] Подключение Client к Server (REST API + WebSocket)
- [ ] Live-обновление позиций агентов
- [ ] Heatmap загруженности (цвет = load/capacity)
- [ ] Контроли симуляции (start/pause/reset)
- [ ] Отображение метрик (avg_time, max_load, throughput)

**UI компоненты:**
- [ ] Кнопки: Start, Pause, Reset, Speed (1x, 2x, 5x, 10x)
- [ ] Слайдер: agents_per_sec (5, 10, 20, 50, 100)
- [ ] Таблица метрик (обновляется каждую сек)
- [ ] Heatmap (цвета рёбер обновляются в реальном времени)

---

### Этап 6: Документация и отчёт (Неделя 4)

**Цель:** Готовая документация и результаты

- [ ] README.md — как запустить систему
- [ ] ARCHITECTURE.md — описание компонентов
- [ ] Эксперимент: baseline vs smart (графики, таблицы)
- [ ] LaTeX отчёт для диссертации
- [ ] Запись демо (видео симуляции)

---

### Временная шкала R&D-1

```
Неделя 1:    ██░░░░░░░░ Инфраструктура (сервер, БД, конфиг)
Неделя 1-2:  ░██░░░░░░░ Симуляция (ядро физики)
Неделя 2:    ░░██░░░░░░ Маршрутизация (A*, K-routes)
Неделя 2-3:  ░░░██░░░░░ Координатор (распределение)
Неделя 3:    ░░░░██░░░░ Интеграция (UI, WebSocket)
Неделя 4:    ░░░░░░██░░ Документация и отчёт

Финальная демонстрация:
├─ Baseline: 1000 агентов на один маршрут → avg_time=240 мин
├─ Smart: 1000 агентов распределены → avg_time=90 мин
└─ Улучшение: 62%
```

---

## Финальный чеклист для разработки

### Архитектура ✅

- [x] Разделение на компоненты (Client, Server, Simulator, Coordinator, Routing, DB)
- [x] Четкие интерфейсы между компонентами
- [x] Независимость компонентов
- [x] Конфигурируемость параметров

### Code Structure

- [ ] Все параметры в `config/` (ни хардкода!)
- [ ] Каждый компонент = отдельный модуль
- [ ] Интерфейсы (ABC) для расширяемости
- [ ] Типизация (type hints везде)
- [ ] Логирование (structured logging)

### Тестирование

- [ ] Unit tests для каждого компонента
- [ ] Integration tests для взаимодействия
- [ ] Сценарии (baseline, smart, edge cases)

### Документация

- [ ] README.md (как запустить)
- [ ] ARCHITECTURE.md (общее описание)
- [ ] API docs (REST endpoints, WebSocket)
- [ ] Комментарии в коде (docstrings)

### Демонстрация

- [ ] Работающая UI с live-обновлениями
- [ ] Таблица результатов (baseline vs smart)
- [ ] Видео симуляции на 1000 агентов
- [ ] Метрики (avg_time, max_load, throughput)

---

## Ключевые Insights

### 1. Граф = Статическая структура

```
Граф не меняется!
- Узлы и рёбра = фиксированы
- Динамичны только:
  - current_load (на каждом ребре)
  - effective_speed (зависит от load)
```

### 2. Симуляция vs MAS

```
Симуляция = Физика (Где агент? С какой скоростью?)
MAS = Интеллект (Какой маршрут выбрать? Как распределить?)

Независимые системы, работают параллельно!
```

### 3. Узкие места

```
e1: capacity=200, может load=198 → затор
e2: capacity=2040, обычно load=30 → свободна

Координатор выявляет bottlenecks и распределяет
новых агентов в обход!
```

### 4. Формула скорости — сердце системы

```
Текущая: effective_speed = speed_limit * (1 - alpha * congestion ** beta)

Параметры которые нужно варьировать:
- alpha (0.5 до 1.0): насколько сильно пробка влияет
- beta (1.0 до 2.0): нелинейность эффекта
- min_speed_ratio (0.05 до 0.2): минимальная скорость

ВСЕ параметры в config.yaml!
```

---

## Контакт с Агентом

**Когда передаёшь этот документ агенту:**

```
"Вот полная архитектура MAS Navigation System.

Текущее состояние:
✅ PyQt5 + MapLibre UI
✅ OSM данные загружены
✅ Граф отображается на карте

Нужно реализовать:

1. Server (FastAPI) с REST/WebSocket
2. Simulator (дискретная симуляция агентов)
3. RoutingEngine (A* с динамическими весами)
4. Coordinator (распределение агентов)
5. Конфигурация (YAML, конфигурируемые параметры)

Все детали, примеры кода и формулы в документе выше.

Начни с Этапа 1 (Инфраструктура).
Спросишь если что-то не понятно!"
```

---

**Документ завершён. Готово к передаче агенту! 🚀**
