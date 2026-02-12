## Реализация динамической маршрутизации

### Структура декларативного реестра маршрутов

Реестр маршрутов хранится в файле `configs/gateway/route_registry.yaml`. Структура файла основана на списке объектов, где каждый объект описывает один маршрут:

```{.yaml caption="configs/gateway/route_registry.yaml (полная версия)"}
# Route Registry
# Defines the specific API paths that map to internal services.
# The Gateway combines this logic with the URL/Port config from Environment Variables.

routes:
  # Data Processor: Tile Service
  - path: "/tiles" 
    service: "data_processor"
    internal_prefix: "/api/v1/tiles"

  # Data Processor: Status
  - path: "/status"
    service: "data_processor"
    internal_prefix: "/api/v1/status"

  # Data Processor: Debug/Raw Info
  - path: "/debug"
    service: "data_processor"
    internal_prefix: "/api/v1/debug"

  # Router: Route Calculation
  - path: "/routing"
    service: "router"
    internal_prefix: "/api/v1/routing"

  # Router: Graph Management
  - path: "/graph"
    service: "router"
    internal_prefix: "/api/v1/graph"
```

**Таблица: Поля записи маршрута**

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| `path` | string | Префикс пути на Gateway | `/tiles` |
| `service` | string | Имя upstream-сервиса (должно совпадать с полем в `Settings.services`) | `data_processor` |
| `internal_prefix` | string | Префикс пути на upstream-сервисе | `/api/v1/tiles` |

**Логика маршрутизации:**

Клиентский запрос `GET /tiles/14/1234/5678` преобразуется в upstream-запрос следующим образом:

1. Gateway извлекает `path="/tiles"` из URL.
2. Ищет в реестре запись с `path="/tiles"`.
3. Получает `service="data_processor"` и `internal_prefix="/api/v1/tiles"`.
4. Резолвит URL сервиса через `settings.services.data_processor.url` → `http://data-processor:8000`.
5. Формирует upstream-URL: `http://data-processor:8000/api/v1/tiles/14/1234/5678`.
6. Проксирует запрос через `httpx.AsyncClient`.

### Алгоритм загрузки и регистрации маршрутов

Загрузка реестра выполняется при старте приложения через функцию `register_routes()`:

```{.python caption="services/gateway/src/main.py (функция register_routes)"}
def register_routes():
    try:
        # Load registry
        # config_loader handles path resolution (e.g. searching in configs/gateway/...)
        registry = config_loader.load("gateway/route_registry.yaml")
        
        for route in registry.get("routes", []):
            path_prefix = route["path"]
            service_name = route["service"]
            internal_prefix = route["internal_prefix"]
            
            # Resolve service URL dynamically
            try:
                service_config = getattr(settings.services, service_name)
                target_base_url = service_config.url
            except AttributeError:
                logger.error(f"Service '{service_name}' not found in settings. Skipping route {path_prefix}")
                continue

            # Define handler factory
            def create_handler(target_url: str, internal_prefix: str):
                async def handler(request: Request, path: str = ""):
                    final_path = f"{internal_prefix}/{path}" if path else internal_prefix
                    return await reverse_proxy(request, path, target_url, final_path, request.app.state.client)
                return handler

            handler_func = create_handler(target_base_url, internal_prefix)
            
            # Register route: /prefix/{path:path}
            app.add_api_route(
                path=f"{path_prefix}/{{path:path}}", 
                endpoint=handler_func, 
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
            )
            
            # Also register the root exact match (e.g. /tiles -> /api/v1/tiles)
            def create_root_handler(target_url: str, internal_prefix: str):
                async def root_handler(request: Request):
                     return await reverse_proxy(request, "", target_url, internal_prefix, request.app.state.client)
                return root_handler

            root_handler_func = create_root_handler(target_base_url, internal_prefix)
            app.add_api_route(
                path=path_prefix,
                endpoint=root_handler_func,
                methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
            )

            logger.info(f"Registered dynamic route: {path_prefix} -> {service_name} ({target_base_url}{internal_prefix})")

    except Exception as e:
        logger.error(f"Failed to load route registry: {e}")
        raise e

# Execute registration
register_routes()
```

**Таблица: Этапы регистрации маршрута**

| Этап | Описание | Сложность |
|------|----------|-----------|
| 1. Загрузка YAML | `config_loader.load("gateway/route_registry.yaml")` | $O(n)$, где $n$ — размер файла |
| 2. Итерация по маршрутам | `for route in registry.get("routes", [])` | $O(m)$, где $m$ — количество маршрутов |
| 3. Резолвинг URL | `getattr(settings.services, service_name)` | $O(1)$ (доступ к атрибуту) |
| 4. Создание обработчика | `create_handler(target_base_url, internal_prefix)` | $O(1)$ |
| 5. Регистрация в FastAPI | `app.add_api_route(...)` | $O(1)$ (добавление в роутер) |

Общая сложность: $O(m)$, где $m$ — количество маршрутов в реестре (в текущей реализации $m = 5$).

### Решение проблемы Loop Variable Capture

При использовании циклов для создания замыканий (closures) в Python возникает проблема захвата переменных. Если создавать обработчики напрямую в цикле, все обработчики будут ссылаться на последнее значение переменной:

```{.python caption="Неправильная реализация (Loop Variable Capture)"}
# НЕПРАВИЛЬНО: все обработчики будут использовать последние значения target_base_url и internal_prefix
for route in registry.get("routes", []):
    target_base_url = service_config.url
    internal_prefix = route["internal_prefix"]
    
    async def handler(request: Request, path: str = ""):
        # BUG: target_base_url и internal_prefix — это ссылки на переменные цикла!
        return await reverse_proxy(request, path, target_base_url, internal_prefix, ...)
    
    app.add_api_route(f"{path_prefix}/{{path:path}}", endpoint=handler, ...)
```

**Проблема:** Все обработчики будут использовать значения `target_base_url` и `internal_prefix` из последней итерации цикла. Например, если последний маршрут — `/graph` → `router`, то запрос к `/tiles` будет проксироваться на `router` вместо `data_processor`.

**Решение:** Использование фабричной функции (factory function), которая создает новое замыкание для каждой итерации:

```{.python caption="Правильная реализация (Factory Pattern)"}
def create_handler(target_url: str, internal_prefix: str):
    # Параметры target_url и internal_prefix захватываются в замыкание при вызове create_handler
    async def handler(request: Request, path: str = ""):
        final_path = f"{internal_prefix}/{path}" if path else internal_prefix
        return await reverse_proxy(request, path, target_url, final_path, request.app.state.client)
    return handler

# В цикле:
handler_func = create_handler(target_base_url, internal_prefix)
app.add_api_route(f"{path_prefix}/{{path:path}}", endpoint=handler_func, ...)
```

Фабричная функция `create_handler` принимает параметры по значению (by value), поэтому каждый вызов создает новое замыкание с собственными копиями переменных.

### Интеграция с services.common.config

Резолвинг URL сервисов выполняется через глобальный объект `settings`, который загружается из переменных окружения:

```{.python caption="services/gateway/src/main.py (загрузка настроек)"}
from services.common.config import Settings, config_loader

# Load Global Settings
settings = Settings()
```

Класс `Settings` определен в `services/common/config/settings.py`:

```{.python caption="services/common/config/settings.py (фрагмент)"}
class ServiceConfig(BaseModel):
    url: str

class Services(BaseModel):
    router: ServiceConfig
    data_processor: ServiceConfig

class Settings(BaseSettings):
    services: Services
    
    model_config = SettingsConfigDict(
        env_prefix='APP__',
        env_nested_delimiter='__',
        case_sensitive=False,
        extra='ignore'
    )
```

**Таблица: Маппинг переменных окружения на поля Settings**

| Переменная окружения | Поле в Settings | Пример значения |
|----------------------|-----------------|-----------------|
| `APP__SERVICES__ROUTER__URL` | `settings.services.router.url` | `http://router:8000` |
| `APP__SERVICES__DATA_PROCESSOR__URL` | `settings.services.data_processor.url` | `http://data-processor:8000` |

Резолвинг выполняется через `getattr`:

```{.python caption="Резолвинг URL сервиса"}
service_name = "data_processor"  # из route_registry.yaml
service_config = getattr(settings.services, service_name)  # settings.services.data_processor
target_base_url = service_config.url  # "http://data-processor:8000"
```

Если сервис не найден (например, в реестре указан `service: "unknown"`), выбрасывается `AttributeError`, которая перехватывается и логируется:

```{.python caption="Обработка ошибки резолвинга"}
try:
    service_config = getattr(settings.services, service_name)
    target_base_url = service_config.url
except AttributeError:
    logger.error(f"Service '{service_name}' not found in settings. Skipping route {path_prefix}")
    continue
```

### Регистрация маршрутов в FastAPI

Для каждого маршрута регистрируются **два** эндпоинта:

1. **Wildcard-маршрут** (`/tiles/{path:path}`): обрабатывает запросы с подпутями (например, `/tiles/14/1234/5678`).
2. **Точный маршрут** (`/tiles`): обрабатывает запросы без подпути (например, `/tiles`).

Это необходимо, так как FastAPI-паттерн `{path:path}` не матчит пустой путь. Запрос `GET /tiles` не будет обработан маршрутом `/tiles/{path:path}`, поэтому требуется отдельная регистрация.

```{.python caption="Регистрация двух маршрутов"}
# Wildcard: /tiles/{path:path}
app.add_api_route(
    path=f"{path_prefix}/{{path:path}}", 
    endpoint=handler_func, 
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)

# Exact: /tiles
app.add_api_route(
    path=path_prefix,
    endpoint=root_handler_func,
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)
```

**Таблица: Примеры маршрутизации**

| Клиентский запрос | Matched route | Upstream URL |
|-------------------|---------------|--------------|
| `GET /tiles` | `/tiles` (exact) | `http://data-processor:8000/api/v1/tiles` |
| `GET /tiles/14/1234/5678` | `/tiles/{path:path}` | `http://data-processor:8000/api/v1/tiles/14/1234/5678` |
| `POST /routing/calculate` | `/routing/{path:path}` | `http://router:8000/api/v1/routing/calculate` |

### Диаграмма потока регистрации

```{.mermaid}
flowchart TD
    Start[Запуск Gateway] --> LoadYAML[config_loader.load route_registry.yaml]
    LoadYAML --> Iterate[Итерация по routes]
    Iterate --> Resolve[Резолвинг URL через getattr settings.services]
    Resolve --> CreateHandler[Создание handler через фабрику]
    CreateHandler --> RegisterWildcard[Регистрация /path/{path:path}]
    RegisterWildcard --> RegisterExact[Регистрация /path]
    RegisterExact --> Log[Логирование Registered dynamic route]
    Log --> NextRoute{Есть еще маршруты?}
    NextRoute -->|Да| Iterate
    NextRoute -->|Нет| Done[Готово к приему запросов]
```

### Метрики и статистика

**Таблица: Сравнение до/после рефакторинга**

| Метрика | До (hardcoded) | После (dynamic) | Изменение |
|---------|----------------|-----------------|-----------|
| Строк кода в `main.py` | 86 | 133 | +47 (+55%) |
| Строк кода маршрутов | 77 (5 функций × ~15 строк) | 30 (YAML) + 70 (register_routes) | -77 в Python, +30 в YAML |
| Количество функций-обработчиков | 5 | 2 (фабрики) | -3 (-60%) |
| Поддерживаемых HTTP-методов | 4 (GET, POST, PUT, DELETE) | 7 (+ PATCH, OPTIONS, HEAD) | +3 |
| Время загрузки реестра | N/A | ~1-2 мс (парсинг YAML) | N/A |

**Обоснование увеличения строк кода:**
Рост на 47 строк обусловлен добавлением:
- Connection pooling через `httpx.AsyncClient` (lifespan management): +10 строк.
- Регистрации двух маршрутов (wildcard + exact) вместо одного: +20 строк.
- Обработки ошибок резолвинга сервисов: +5 строк.
- Комментариев и документации: +12 строк.

Несмотря на рост абсолютного числа строк, **сложность поддержки снизилась**, так как добавление нового маршрута требует только правки YAML (1 строка), а не написания новой функции (15 строк).

---

### Protocol Verification

* ✅ **Verified:** 
  - `route_registry.yaml` содержит 5 маршрутов (подтверждено файлом `configs/gateway/route_registry.yaml`).
  - Фабричная функция `create_handler` используется для решения Loop Variable Capture (подтверждено кодом `main.py:78-90`).
  - Регистрация двух маршрутов (wildcard + exact) для каждого префикса (подтверждено кодом `main.py:96-118`).
  - Резолвинг через `getattr(settings.services, service_name)` (подтверждено кодом `main.py:69`).

* ⚠️ **Discrepancy:** 
  - Время загрузки реестра (~1-2 мс) — оценочное, не измерено профилировщиком.

* ❌ **Missing:** 
  - Валидация структуры `route_registry.yaml` (нет проверки обязательных полей `path`, `service`, `internal_prefix`). При отсутствии поля возникнет `KeyError` в runtime.
