# Логирование в Navigation MAS

## Архитектура логирования

Система использует **loguru** для zero-cost logging с интеграцией в **Grafana Loki** для быстрого поиска проблем.

### Компоненты

```
Application → loguru → JSON files → Promtail → Loki → Grafana
                  ↓
              stdout (colored)
```

### Файлы логов

Все логи хранятся в `.agent_dir/logs/`:

- **`app.jsonl`** - все логи приложения (JSON Lines format)
- **`errors.jsonl`** - только ERROR и выше (быстрый поиск ошибок)
- **`slow_operations.jsonl`** - операции длительностью >1 секунды

### Уровни логирования

- **TRACE** (5) - вход/выход каждой функции (декораторы)
- **DEBUG** (10) - детали выполнения, промежуточные результаты
- **INFO** (20) - важные события (стандартно включен)
- **SUCCESS** (25) - успешные завершения операций
- **WARNING** (30) - предупреждения
- **ERROR** (40) - ошибки
- **CRITICAL** (50) - критичные ошибки

## Использование

### Базовое логирование

```python
from loguru import logger

# Простое логирование
logger.info("Processing started", batch_size=100)

# Структурированное логирование с контекстом
logger.debug("Algorithm selected", algorithm="v2.1", version="2.1.3")

# Логирование ошибок
try:
    risky_operation()
except Exception as e:
    logger.exception("Operation failed", operation="risky")
```

### Автоматическая инструментация функций

```python
from src.utils.instrumentation import log_function

@log_function("DEBUG")
def process_route(route_id: int, user_id: str):
    """Function is automatically logged on entry/exit."""
    result = calculate_route(route_id)
    return result

# Логи:
# → process_route (args: route_id=123, user_id="user_456")
# ← process_route (duration_ms: 1234.56)
```

### Zero-cost для дорогих операций

```python
# BAD ❌ - expensive_computation() вызывается ВСЕГДА
logger.debug(f"Result: {expensive_computation()}")

# GOOD ✓ - функция вызывается только если DEBUG включен
logger.opt(lazy=True).debug(
    "Result: {}",
    lambda: expensive_computation()
)
```

### Контекст для распределенного трейсинга

```python
from src.utils.instrumentation import set_agent_context, log_with_context

# Установить контекст агента
token = set_agent_context(
    agent_id="agent_001",
    task_id="task_123",
    user_id="user_456"
)

try:
    # Все логи будут иметь этот контекст
    log_with_context("Task started", priority="high")
    process_task()
    log_with_context("Task completed")
finally:
    agent_context.reset(token)
```

### Асинхронные функции

```python
from src.utils.instrumentation import log_async_function

@log_async_function("DEBUG")
async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()
```

## Grafana Loki

### Запуск

```bash
# Запустить все сервисы (включая Loki, Promtail, Grafana)
docker-compose up -d

# Grafana доступна на http://localhost:3000
# Логин: admin / admin
```

### Поиск логов в Grafana

1. Открыть Grafana: http://localhost:3000
2. Добавить Loki как Data Source (если не добавлен автоматически):
   - URL: http://loki:3100
3. Перейти в Explore
4. Выбрать Loki data source
5. Запросы (LogQL):

```logql
# Все логи приложения
{job="app_logs"}

# Только ошибки
{job="error_logs"}

# Ошибки за последний час
{job="error_logs"} |= "ERROR"

# Медленные операции (>5 секунд)
{job="slow_operations"} | json | duration_ms > 5000

# Логи конкретной функции
{job="app_logs"} | json | function="process_route"

# Логи конкретного агента
{job="app_logs"} | json | agent_id="agent_001"

# Все исключения
{job="app_logs"} | json | exception_type != ""

# Комбинированный запрос
{job="app_logs"} 
  | json 
  | level="ERROR" 
  | function=~"process.*"
  | line_format "{{.timestamp}} [{{.level}}] {{.function}}: {{.message}}"
```

### Dashboard для быстрого мониторинга

Создать dashboard в Grafana:

**Panel 1: Errors per minute**
```logql
rate({job="error_logs"}[1m])
```

**Panel 2: Slow operations count**
```logql
count_over_time({job="slow_operations"}[5m])
```

**Panel 3: Average duration by function**
```logql
avg_over_time(
  {job="app_logs"} | json | duration_ms > 0 | unwrap duration_ms [5m]
) by (function)
```

## Конфигурация

### Изменение уровня логирования

```python
# src/utils/loguru_config.py
configure_loguru(
    log_level="DEBUG",  # Изменить на TRACE, INFO, WARNING, etc.
    log_to_file=True,
    json_logs=True
)
```

### Отключение JSON логов (только console)

```python
configure_loguru(
    log_level="INFO",
    log_to_file=False,  # Отключить файловое логирование
    json_logs=False
)
```

### Production конфигурация

```python
# Только WARNING и выше для минимизации overhead
configure_loguru(
    log_level="WARNING",
    log_to_file=True,
    json_logs=True
)
```

## Best Practices

### ✅ DO

```python
# Структурированное логирование
logger.info("Route calculated", 
    route_id=123, 
    distance_km=45.6,
    duration_sec=1234
)

# Lazy evaluation для дорогих операций
logger.opt(lazy=True).debug("Stats: {}", calculate_stats)

# Контекст для трейсинга
set_agent_context(agent_id=agent_id, task_id=task_id)
log_with_context("Processing", step="validation")
```

### ❌ DON'T

```python
# НЕ логировать sensitive данные
logger.info(f"User {user_id} password: {password}")  # ❌

# НЕ использовать f-strings для дорогих операций
logger.debug(f"Result: {expensive_computation()}")  # ❌

# НЕ логировать в циклах без проверки уровня
for item in large_list:
    logger.debug(f"Processing {item}")  # ❌ (миллионы логов)
```

## Troubleshooting

### Логи не появляются в Grafana

1. Проверить, что Promtail запущен:
   ```bash
   docker-compose logs promtail
   ```

2. Проверить, что файлы логов существуют:
   ```bash
   ls -lh .agent_dir/logs/
   ```

3. Проверить Promtail конфигурацию:
   ```bash
   docker-compose exec promtail cat /etc/promtail/config.yml
   ```

### Слишком много логов

1. Повысить уровень логирования (INFO → WARNING)
2. Отключить TRACE уровень декораторов
3. Использовать фильтры в Promtail

### Performance overhead

- **Zero-cost guarantee**: если уровень отключен, код практически не выполняется
- Используйте `logger.opt(lazy=True)` для дорогих операций
- Async file writes (`enqueue=True`) не блокируют основной поток
- JSON сериализация оптимизирована loguru

## Ссылки

- [Loguru Documentation](https://loguru.readthedocs.io/)
- [Grafana Loki Documentation](https://grafana.com/docs/loki/)
- [LogQL Syntax](https://grafana.com/docs/loki/latest/logql/)
- [Agent Logging Guide](.github/agent_logging_guide.md)
