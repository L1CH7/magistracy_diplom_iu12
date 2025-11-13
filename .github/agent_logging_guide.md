# Центральное логирование для AI-агентов: Полный гайд

## TL;DR — Что выбрать?

| Требование | Решение |
|-----------|----------|
| **а) Быстрое обнаружение проблем** | Grafana Loki (lightweight, native Grafana integration) |
| **б) Интеграция с Loguru** | Встроенный JSON handler или `loki-logger-handler` |
| **в) Максимальное покрытие с zero-cost** | Decorators + структурированное логирование + contextvars |

---

## Часть A: Технология для fast detection — Grafana Loki

### Почему Loki, а не ELK/Datadog?

**Loki vs ELK Stack**:
- **Ложе хранится** без индексирования содержимого (只индексирует labels)
- **10-50x дешевле** чем Elasticsearch
- **2-3 минуты setup** vs недели для ELK
- **Native Grafana** — переключаетесь между метриками и логами в один клик
- **Отлично масштабируется** для single-node и кластеров

**Loki vs Datadog**:
- Loki — open-source, вы контролируете данные
- Datadog — SaaS, дороже, но полнее фичей

### Docker Compose Setup (2 минуты)

```yaml
version: '3.8'

services:
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    volumes:
      - loki-storage:/tmp/loki
    command: -config.file=/etc/loki/local-config.yaml
    environment:
      - TZ=Europe/Moscow

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/log:/var/log
      - ./promtail-config.yaml:/etc/promtail/config.yml
    command: -config.file=/etc/promtail/config.yml
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana
    depends_on:
      - loki

volumes:
  loki-storage:
  grafana-storage:
```

Запуск:
```bash
docker-compose up -d
# Графана доступна на localhost:3000
# Логи попадают в Loki (localhost:3100)
```

---

## Часть B: Integratio Loguru + Loki

### Способ 1: JSON handler (рекомендуется)

```python
# logging_config.py
import json
import sys
from loguru import logger
from datetime import datetime

# Удаляем default stderr handler
logger.remove()

def json_formatter(record):
    """Форматирует лог в JSON для Loki"""
    data = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "message": record["message"],
        "function": record["function"],
        "line": record["line"],
        "module": record["module"],
        "process_id": record["process"].id,
        "thread_id": record["thread"].id,
        # Добавляем extra поля (контекст)
        **record["extra"]
    }
    return json.dumps(data, ensure_ascii=False) + "\n"

# stdout — для development (красивый формат)
logger.add(
    sys.stdout,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    colorize=True,
    filter=lambda record: record["level"].name not in ["TRACE", "SPAM"]  # Исключаем мусор
)

# JSON в файл — для Loki/сбора (Promtail будет читать этот файл)
logger.add(
    "logs/app.jsonl",  # JSON Lines формат
    level="TRACE",
    format=json_formatter,
    rotation="500 MB",
    retention="7 days"
)

# Отдельный файл для ошибок
logger.add(
    "logs/errors.jsonl",
    level="ERROR",
    format=json_formatter,
    rotation="100 MB"
)

# Для профилактики — логирование медленных операций
def log_performance(record):
    """Фильтр для логирования только медленных операций"""
    if "duration_ms" in record["extra"]:
        return record["extra"]["duration_ms"] > 1000  # > 1 сек
    return True

logger.add(
    "logs/slow_operations.jsonl",
    level="INFO",
    format=json_formatter,
    filter=log_performance
)
```

### Способ 2: loki-logger-handler (direct to Loki)

```python
# requirements.txt
loguru==0.7.0
loki-logger-handler==0.2.0

# main.py
from loguru import logger
from loki_logger_handler.loki_logger_handler import LokiLoggerHandler
from loki_logger_handler.formatters.loguru_formatter import LoguruFormatter
import os

# Прямая отправка в Loki (без файлов)
loki_handler = LokiLoggerHandler(
    url=os.getenv("LOKI_URL", "http://localhost:3100"),
    labels={
        "application": "my_agent",
        "environment": "development",
        "service": "core",
    },
    timeout=10
)

# Настраиваем Loguru с Loki handler'ом
logger.configure(
    handlers=[
        {
            "sink": loki_handler,
            "format": "{message}",
            "serialize": True,  # JSON формат
            "level": "DEBUG"
        }
    ]
)

logger.info("Application started")
```

### Способ 3: Гибридный (файл + Loki)

```python
# В docker-compose добавляем Promtail конфиг:

# promtail-config.yaml
clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: system
    static_configs:
      - targets:
          - localhost
        labels:
          job: app_logs
          __path__: /var/log/app/*.jsonl

  - job_name: app_errors
    static_configs:
      - targets:
          - localhost
        labels:
          job: error_logs
          severity: error
          __path__: /var/log/app/errors.jsonl

  - job_name: slow_operations
    static_configs:
      - targets:
          - localhost
        labels:
          job: performance
          __path__: /var/log/app/slow_operations.jsonl
```

---

## Часть C: Максимальное покрытие функций (Zero-Cost disabling)

### 1. Decorator для auto-instrumentation

```python
# instrumentation.py
from functools import wraps
from loguru import logger
import time
from typing import Any, Callable
import inspect

def log_function(level: str = "DEBUG", include_args: bool = True, include_result: bool = True):
    """
    Decorator для логирования всех функций.
    
    Zero-cost: если нет handler'а для уровня DEBUG, код практически не выполняется.
    
    Использование:
        @log_function("TRACE")
        def my_function(x, y):
            return x + y
    """
    def decorator(func: Callable) -> Callable:
        # Получаем сигнатуру функции один раз
        sig = inspect.signature(func)
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Логирование ВХОДА
            context = {
                "function": func.__name__,
                "module": func.__module__,
            }
            
            if include_args:
                # Связываем имена параметров с значениями
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                context["args"] = dict(bound.arguments)
            
            logger.log(
                level,
                f"→ Calling {func.__name__}",
                **context
            )
            
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                # Логирование ВЫХОДА
                if include_result:
                    logger.log(
                        level,
                        f"← {func.__name__} returned successfully",
                        duration_ms=duration_ms,
                        result=str(result)[:500],  # Первые 500 символов
                        function=func.__name__
                    )
                else:
                    logger.log(
                        level,
                        f"← {func.__name__} completed",
                        duration_ms=duration_ms,
                        function=func.__name__
                    )
                
                return result
            
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.exception(
                    f"✗ {func.__name__} failed with {type(e).__name__}",
                    duration_ms=duration_ms,
                    function=func.__name__,
                    exception_type=type(e).__name__
                )
                raise
        
        return wrapper
    return decorator

# Использование
@log_function("TRACE")
def process_user_data(user_id: int, action: str) -> bool:
    """Обработка данных пользователя"""
    time.sleep(0.1)  # Имитация работы
    return True

@log_function("DEBUG", include_args=False)  # Скрываем аргументы (могут быть sensitive)
def fetch_api_key() -> str:
    """Получение API ключа"""
    return "secret-key-12345"

# Вызов
process_user_data(123, "update")
fetch_api_key()
```

### 2. Context propagation для AI-агента

```python
# agent_context.py
import contextvars
from typing import Dict, Any
from loguru import logger

# Contextvars для безопасности в async коде
agent_context = contextvars.ContextVar("agent_context", default={})
request_id_var = contextvars.ContextVar("request_id", default="unknown")
user_id_var = contextvars.ContextVar("user_id", default="anonymous")
trace_id_var = contextvars.ContextVar("trace_id", default="")

def set_agent_context(**kwargs):
    """Устанавливает контекст для всех последующих логов в этом потоке"""
    current = agent_context.get().copy()
    current.update(kwargs)
    token = agent_context.set(current)
    return token

def log_with_context(message: str, level: str = "INFO", **extra):
    """Логирует сообщение с автоматическим контекстом"""
    context = agent_context.get().copy()
    context.update({
        "request_id": request_id_var.get(),
        "user_id": user_id_var.get(),
        "trace_id": trace_id_var.get(),
    })
    context.update(extra)
    logger.log(level, message, **context)

# Использование в AI-агенте
class AIAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
    
    @log_function("DEBUG")
    def process_task(self, task_id: str, user_id: str):
        """Обработка задачи агентом"""
        # Устанавливаем контекст для этой задачи
        user_id_var.set(user_id)
        set_agent_context(
            agent_id=self.agent_id,
            task_id=task_id,
            stage="initialization"
        )
        
        log_with_context(
            "Task processing started",
            task_type="data_analysis",
            priority="high"
        )
        
        # Все вложенные вызовы будут иметь этот контекст
        self._validate_input()
        self._execute_logic()
        
        log_with_context("Task processing completed")
    
    @log_function("TRACE")  # Это будет TRACE — контролируется уровнем handler'а
    def _validate_input(self):
        log_with_context("Validating input data", stage="validation")
    
    @log_function("TRACE")
    def _execute_logic(self):
        log_with_context("Executing business logic", stage="execution")
```

### 3. Структурированное логирование для трейсинга

```python
# structured_logging.py
from enum import Enum
from loguru import logger
import json

class EventType(Enum):
    """Типы событий для структурированного логирования"""
    FUNCTION_ENTRY = "fn_entry"
    FUNCTION_EXIT = "fn_exit"
    FUNCTION_ERROR = "fn_error"
    DECISION = "decision"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VALIDATION = "validation"
    DATA_TRANSFORM = "data_transform"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"

class StructuredLogger:
    """Структурированное логирование для агентов"""
    
    @staticmethod
    def log_event(
        event_type: EventType,
        message: str,
        level: str = "INFO",
        **context
    ):
        """Логирует структурированное событие"""
        context["event_type"] = event_type.value
        logger.log(level, message, **context)
    
    @staticmethod
    def log_tool_call(tool_name: str, input_data: Dict[str, Any], **context):
        """Логирует вызов tool'а"""
        StructuredLogger.log_event(
            EventType.TOOL_CALL,
            f"Tool called: {tool_name}",
            tool_name=tool_name,
            input_data=input_data,
            **context
        )
    
    @staticmethod
    def log_decision(decision: str, confidence: float, reason: str, **context):
        """Логирует решение агента"""
        StructuredLogger.log_event(
            EventType.DECISION,
            f"Agent decision: {decision}",
            level="DEBUG",
            decision=decision,
            confidence=confidence,
            reason=reason,
            **context
        )
    
    @staticmethod
    def log_validation(
        validation_name: str,
        passed: bool,
        details: str,
        **context
    ):
        """Логирует валидацию"""
        level = "DEBUG" if passed else "WARNING"
        StructuredLogger.log_event(
            EventType.VALIDATION,
            f"Validation '{validation_name}': {'✓' if passed else '✗'}",
            level=level,
            validation_name=validation_name,
            passed=passed,
            details=details,
            **context
        )

# Использование
agent = AIAgent("agent_001")
StructuredLogger.log_tool_call(
    tool_name="database_query",
    input_data={"query": "SELECT * FROM users", "limit": 10},
    task_id="task_123"
)

StructuredLogger.log_decision(
    decision="use_cached_result",
    confidence=0.95,
    reason="Cache hit for identical query within 5 minutes",
    task_id="task_123"
)
```

### 4. Покрытие с разными уровнями (для гибкости отключения)

```python
# levels_coverage.py
from loguru import logger

# Уровни в порядке возрастания (от самого многословного к самому критичному):
# TRACE (5) — вход/выход каждой функции
# DEBUG (10) — детали выполнения, промежуточные результаты
# INFO (20) — важные события (стандартно включен)
# SUCCESS (25) — успешные завершения
# WARNING (30) — предупреждения
# ERROR (40) — ошибки
# CRITICAL (50) — критичные ошибки

class Agent:
    @log_function("TRACE")  # Видно только при явном включении TRACE
    def process(self):
        logger.trace("Function signature validated")
        
        # DEBUG — детали
        logger.debug("Algorithm selected: strategy_v2", algorithm_version="2.1")
        
        # INFO — события
        logger.info("Processing started", batch_size=100)
        
        # SUCCESS (custom уровень)
        logger.success("Data transformed successfully", rows_processed=100)
        
        # WARNING — предупреждение
        if processing_time > threshold:
            logger.warning(
                "Processing slow",
                duration_ms=processing_time,
                threshold_ms=threshold
            )
        
        # ERROR — ошибка обработана
        try:
            self.validate()
        except ValidationError as e:
            logger.error("Validation failed", error=str(e))
        
        # CRITICAL — агент не может продолжать
        if not self.essential_service_available():
            logger.critical("Essential service unavailable")

# Конфигурация handlers с разными уровнями:

logger.remove()

# Production: только WARNING и выше
logger.add(
    "logs/app.jsonl",
    level="WARNING",
    format=json_formatter,
    rotation="500 MB"
)

# Development: все до DEBUG
logger.add(
    sys.stdout,
    level="DEBUG",
    format="{time} | {level} | {message}"
)

# Если нужно глубокое дебаггирование:
# logger.add(
#     "logs/trace.jsonl",
#     level="TRACE"
# )
```

---

## Лучшие практики

### 1. Не логируйте sensitive data

```python
# BAD ❌
logger.info(f"User {user_id} logged in with password {password}")

# GOOD ✓
logger.info(f"User authentication successful", user_id=user_id)
```

### 2. Используйте lazy evaluation для дорогих операций

```python
# BAD ❌ — expensive_computation() вызывается ВСЕГДА
logger.debug(f"Result: {expensive_computation()}")

# GOOD ✓ — функция вызывается только если DEBUG включен
logger.opt(lazy=True).debug("Result: {x}", x=expensive_computation)
```

### 3. Структурируйте логи для поиска в Loki

```python
# Неправильно (просто строка)
logger.info(f"User {user_id} performed action {action} on resource {resource_id}")

# Правильно (структурированные поля)
logger.info(
    "User action performed",
    user_id=user_id,
    action=action,
    resource_id=resource_id,
    resource_type="document"
)

# Теперь в Loki можно искать:
# {job="app_logs"} | json | action="update" | resource_type="document"
```

### 4. Связывайте логи в распределённых системах

```python
import uuid

# middleware.py (FastAPI)
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(request_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

# Все логи будут иметь request_id
```

---

## Запуск на production

```bash
# docker-compose up -d
# Проверить логи в Grafana (localhost:3000)
# Запрос в Loki:
# {job="app_logs"} | json | level="ERROR"

# Выключить TRACE когда всё работает:
# logger.remove()
# logger.add("logs/app.jsonl", level="INFO")  # INFO и выше
```

### Результат:
✅ Zero CPU если TRACE отключен (логи не вычисляются)
✅ Все функции покрыты логами
✅ Быстрое обнаружение проблем в Grafana
✅ AI-агент может анализировать свои действия
