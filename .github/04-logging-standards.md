# Стандарты логирования

## Формат лога
Стандартный формат:
```
[YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL Message
```

Пример:
```
[2025.10.09 16:38:16.416] {0x7f8872474280} I SerializeToFile result[1]
[2025.10.09 16:38:16.416] {0x7f8872474280} I MainWindow finished
[2025.10.09 16:38:16.421] {0x7f8872474280} W Disconnected nodes found: 15
[2025.10.09 16:38:16.421] {0x7f8872474280} E Failed to load graph from OSM
```

## Уровни логирования
- **T** (Trash): Мусор.
- **T** (Trace): детальная отладочная информация (крайне редко используется).
- **D** (Debug): отладочная информация для разработки.
- **I** (Info): информационные сообщения о нормальной работе.
- **W** (Warning): предупреждения о потенциальных проблемах.
- **E** (Error): ошибки, требующие внимания.
- **F** (Fatal): критические ошибки, после которых система не может работать.

## Цвета для уровней логгирования (только буква для LEVEL)
- **T** (Trash): Черный
- **T** (Trace): Серый
- **D** (Debug): Желтый
- **I** (Info): Белый
- **W** (Warning): Фиолетовый
- **E** (Error): Красный
- **F** (Fatal): Темно-красный

## Python реализация

Создай модуль `logger.py`:

```python
import logging
import threading
from datetime import datetime

class CustomFormatter(logging.Formatter):
    LEVEL_MAP = {
        logging.DEBUG: 'D',
        logging.INFO: 'I',
        logging.WARNING: 'W',
        logging.ERROR: 'E',
        logging.CRITICAL: 'F',
    }

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y.%m.%d %H:%M:%S.%f')[:-3]
        thread_id = f"0x{threading.current_thread().ident:x}"
        level = self.LEVEL_MAP.get(record.levelno, 'I')
        message = record.getMessage()
        return f"[{timestamp}] {{{thread_id}}} {level} {message}"

def setup_logger(name: str, level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    logger.addHandler(handler)

    # File handler с ротацией
    from logging.handlers import RotatingFileHandler
    import os
    os.makedirs('.agent_dir/logs', exist_ok=True)
    file_handler = RotatingFileHandler(
        f'.agent_dir/logs/{name}.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(CustomFormatter())
    logger.addHandler(file_handler)

    return logger
```

Использование:
```python
from logger import setup_logger

logger = setup_logger('routing')

logger.info("Starting route calculation")
logger.warning(f"High load detected: {load_value}")
logger.error(f"Failed to connect to OSRM: {error}")
```

## C++ реализация

Для C++ используй spdlog или создай свой макрос:

```cpp
#include <iostream>
#include <chrono>
#include <thread>
#include <iomanip>
#include <sstream>

#define LOG(level, msg) do {     auto now = std::chrono::system_clock::now();     auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;     auto timer = std::chrono::system_clock::to_time_t(now);     std::tm tm = *std::localtime(&timer);     std::ostringstream oss;     oss << "[" << std::put_time(&tm, "%Y.%m.%d %H:%M:%S") << "." << std::setfill('0') << std::setw(3) << ms.count() << "] ";     oss << "{" << std::hex << std::this_thread::get_id() << "} ";     oss << level << " " << msg;     std::cout << oss.str() << std::endl; } while(0)

#define LOG_INFO(msg) LOG("I", msg)
#define LOG_WARN(msg) LOG("W", msg)
#define LOG_ERROR(msg) LOG("E", msg)
```

Использование:
```cpp
LOG_INFO("Graph loaded: " << node_count << " nodes");
LOG_WARN("Timeout exceeded: " << elapsed_ms << "ms");
LOG_ERROR("Failed to parse OSM file: " << filename);
```

## Что логировать

**Обязательно логируй:**
- Старт/остановка основных компонентов.
- Загрузку конфигурации и данных.
- Сетевые запросы и их результаты.
- Ошибки и исключения с полным stack trace.
- Важные business events (агент создан, маршрут рассчитан, координация завершена).
 - События шины: публикация в Redis Pub/Sub/Streams (ключ, размер батча, latency), приём/отправка WS сообщений (кол-во, дросселирование, пропуски).

**Не логируй:**
- Чувствительные данные (пароли, токены, PII).
- Избыточные детали в production (DEBUG-уровень только в dev).
- Данные в циклах с высокой частотой (логируй агрегаты: "Processed 1000 items in 2.5s").

## Структурированное логирование

Для сложных систем используй JSON logging:

```python
import json
import logging
from datetime import datetime
import threading

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'thread': threading.current_thread().ident,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'request_id': getattr(record, 'request_id', None),
            'agent_id': getattr(record, 'agent_id', None),
            'topic': getattr(record, 'topic', None),
            'batch_size': getattr(record, 'batch_size', None),
        }
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)
```

Это позволяет парсить логи инструментами (ELK, Grafana Loki).

## Контекстное логирование

Используй контекст для добавления метаданных:

```python
import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar('request_id', default='unknown')

class ContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True

# В формате добавь {request_id}
# Пример: "[{timestamp}] [{request_id}] {level} {message}"
```

Это помогает трейсить запросы через всю систему.
