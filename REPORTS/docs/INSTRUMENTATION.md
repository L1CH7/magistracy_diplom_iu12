# Function Instrumentation Guide

## Автоматическое логирование функций с zero-cost

Этот модуль предоставляет декораторы для автоматического логирования входа/выхода функций с нулевой стоимостью когда логирование отключено.

## Когда использовать декораторы

### ✅ Используйте @log_function для:

- **Сложной бизнес-логики** где важно видеть вход/выход
- **API endpoints** для трейсинга запросов
- **Критичных алгоритмов** (pathfinding, route merging, etc.)
- **Медленных операций** где нужно измерить duration_ms

### ❌ НЕ используйте @log_function для:

- **Простых геттеров/сеттеров** (они вызываются слишком часто)
- **Функций в циклах** (миллионы логов)
- **Low-level утилит** (math functions, string helpers)
- **Функций с sensitive данными** (используйте include_args=False)

## Примеры

### Базовое использование

```python
from src.utils.instrumentation import log_function
from loguru import logger

@log_function("DEBUG")
def calculate_route(start_node: int, end_node: int):
    """Calculate shortest route between nodes."""
    logger.info("Starting pathfinding", start=start_node, end=end_node)
    result = dijkstra(start_node, end_node)
    return result

# Logs:
# → calculate_route args={start_node=123, end_node=456}
# Starting pathfinding start=123 end=456
# ← calculate_route duration_ms=1234.56
```

### Скрытие sensitive аргументов

```python
@log_function("DEBUG", include_args=False)
def authenticate_user(password: str, api_key: str):
    """Authenticate user (sensitive data)."""
    return validate_credentials(password, api_key)

# Logs:
# → authenticate_user  (args не логируются)
# ← authenticate_user duration_ms=45.12
```

### Логирование результата

```python
@log_function("DEBUG", include_result=True)
def fetch_weather():
    """Fetch weather data from API."""
    return {"temp": 20, "humidity": 65}

# Logs:
# → fetch_weather
# ← fetch_weather duration_ms=234.56 result={'temp': 20, 'humidity': 65}
```

### Async функции

```python
from src.utils.instrumentation import log_async_function

@log_async_function("DEBUG")
async def fetch_data_from_api(url: str):
    """Fetch data from external API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# Logs:
# → fetch_data_from_api args={url='https://api.example.com/data'}
# ← fetch_data_from_api duration_ms=567.89
```

### Контекст для распределенного трейсинга

```python
from src.utils.instrumentation import (
    set_agent_context,
    log_with_context
)

def process_agent_task(agent_id: str, task_id: str):
    """Process task with automatic context propagation."""
    # Set context for all subsequent logs
    token = set_agent_context(
        agent_id=agent_id,
        task_id=task_id
    )
    
    try:
        log_with_context("Task started", priority="high")
        
        # All nested function calls will have this context
        validate_input()
        execute_logic()
        
        log_with_context("Task completed successfully")
    finally:
        # Restore previous context
        agent_context.reset(token)

# Logs:
# Task started agent_id=agent_001 task_id=t123 priority=high request_id=...
# Task completed successfully agent_id=agent_001 task_id=t123 request_id=...
```

## Уровни логирования для декораторов

```python
# TRACE - очень детально (вход/выход КАЖДОЙ функции)
@log_function("TRACE")  # Видно только при --log-level=TRACE

# DEBUG - детали (важные функции)
@log_function("DEBUG")  # Видно при --log-level=DEBUG

# INFO - важные события
@log_function("INFO")   # Всегда видно (стандартный уровень)
```

## Performance Impact

### Zero-Cost когда отключено

```python
# Если log_level=WARNING, то:
@log_function("DEBUG")
def expensive_operation():
    return heavy_calculation()

# Overhead декоратора: ~0.01ms (проверка уровня)
# НЕ вызывается: bind(), serialize args, write to file
```

### Минимальный overhead когда включено

```python
# Overhead декоратора: ~0.5-1ms
# - time.perf_counter() (2x): ~0.1ms
# - inspect.signature.bind(): ~0.2ms
# - logger.log() (async write): ~0.3ms
```

## Best Practices

### 1. Используйте правильный уровень

```python
# Критичные операции (всегда логировать)
@log_function("INFO")
def start_agent():
    pass

# Детали реализации
@log_function("DEBUG")
def calculate_distance():
    pass

# Трейсинг (только для глубокого дебага)
@log_function("TRACE")
def get_node_neighbors():
    pass
```

### 2. Не логируйте sensitive данные

```python
# BAD ❌
@log_function("DEBUG")  # password will be logged!
def login(user, password):
    pass

# GOOD ✓
@log_function("DEBUG", include_args=False)
def login(user, password):
    logger.info("Login attempt", user=user)  # Log user, not password
    pass
```

### 3. Используйте context для трейсинга

```python
class Agent:
    def __init__(self, agent_id):
        self.agent_id = agent_id
    
    @log_function("DEBUG")
    def process_task(self, task_id):
        # Set context once, all nested calls will have it
        token = set_agent_context(agent_id=self.agent_id, task_id=task_id)
        try:
            self._validate()
            self._execute()
        finally:
            agent_context.reset(token)
```

### 4. Комбинируйте с manual logging

```python
@log_function("DEBUG")
def complex_operation(data):
    logger.debug("Phase 1: validation", records=len(data))
    validated = validate(data)
    
    logger.debug("Phase 2: transformation")
    transformed = transform(validated)
    
    logger.debug("Phase 3: saving", saved_count=len(transformed))
    save(transformed)
    
    return transformed

# Logs:
# → complex_operation args={data=[...]}
# Phase 1: validation records=100
# Phase 2: transformation
# Phase 3: saving saved_count=95
# ← complex_operation duration_ms=456.78
```

## Troubleshooting

### Слишком много логов

```python
# Solution 1: Повысить уровень декоратора
@log_function("TRACE")  # Вместо DEBUG
def frequently_called():
    pass

# Solution 2: Убрать декоратор, добавить manual logging
def frequently_called():
    # Manual logging только для важных событий
    if condition:
        logger.warning("Important event")
```

### Декоратор не работает

```python
# Check 1: Правильный import
from src.utils.instrumentation import log_function  # ✓
from utils.instrumentation import log_function      # ✗

# Check 2: Скобки после декоратора
@log_function("DEBUG")  # ✓
def my_function():
    pass

@log_function  # ✗ WRONG! Missing level
def my_function():
    pass
```

## Примеры покрытия

### API endpoint (FastAPI)

```python
from src.utils.instrumentation import set_agent_context
from loguru import logger

@app.post("/sim/agent/start")
@log_function("INFO")  # INFO level for API endpoints
def start_agent(req: StartAgentRequest):
    token = set_agent_context(
        request_id=request.headers.get("X-Request-ID"),
        user_id=req.user_id
    )
    try:
        logger.info("Starting agent", route_id=req.route_id)
        agent = create_agent(req)
        return {"status": "started", "agent_id": agent.id}
    finally:
        agent_context.reset(token)
```

### Core algorithm

```python
@log_function("DEBUG")
def find_route_intersection(route1, route2, graph):
    """Find common edges between two routes."""
    logger.debug(
        "Finding intersection",
        route1_edges=len(route1['edges']),
        route2_edges=len(route2['edges'])
    )
    
    common = []
    for edge in route1['edges']:
        if edge in route2['edges']:
            common.append(edge)
    
    logger.debug("Intersection found", common_edges=len(common))
    return common
```

## См. также

- [LOGGING.md](LOGGING.md) - общий гайд по логированию
- [agent_logging_guide.md](../.github/agent_logging_guide.md) - детали Loki/Grafana
- [loguru documentation](https://loguru.readthedocs.io/)
