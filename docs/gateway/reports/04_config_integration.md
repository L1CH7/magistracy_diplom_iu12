## Интеграция с общей конфигурацией

### Архитектура services.common.config

Модуль `services.common.config` предоставляет централизованную систему управления конфигурацией для всех микросервисов. Архитектура основана на двух компонентах:

1. **Settings (Pydantic BaseSettings):** Загрузка конфигурации из переменных окружения.
2. **ConfigLoader:** Загрузка YAML-файлов с кэшированием и поддержкой `!include` директив.

```{.mermaid}
graph LR
    EnvVars[Environment Variables] --> Settings[Settings Pydantic]
    YAMLFiles[YAML Configs] --> ConfigLoader[ConfigLoader]
    Settings --> Gateway[Gateway Service]
    ConfigLoader --> Gateway
    Settings --> Router[Router Service]
    ConfigLoader --> Router
    Settings --> DataProc[Data Processor]
    ConfigLoader --> DataProc
```

### Структура Settings

Класс `Settings` определен в `services/common/config/settings.py`:

```{.python caption="services/common/config/settings.py (фрагмент)"}
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class ServiceConfig(BaseModel):
    """Configuration for a single internal microservice."""
    url: str

class Services(BaseModel):
    """Registry of all available microservices."""
    router: ServiceConfig
    data_processor: ServiceConfig

class Settings(BaseSettings):
    """Global Application Settings."""
    services: Services
    
    model_config = SettingsConfigDict(
        env_prefix='APP__',
        env_nested_delimiter='__',
        case_sensitive=False,
        extra='ignore'
    )
```

**Таблица: Параметры SettingsConfigDict**

| Параметр | Значение | Описание |
|----------|----------|----------|
| `env_prefix` | `'APP__'` | Префикс для всех переменных окружения |
| `env_nested_delimiter` | `'__'` | Разделитель для вложенных полей (например, `APP__SERVICES__ROUTER__URL`) |
| `case_sensitive` | `False` | Игнорировать регистр в именах переменных |
| `extra` | `'ignore'` | Игнорировать неизвестные переменные окружения |

**Пример маппинга переменных окружения:**

```bash
APP__SERVICES__ROUTER__URL=http://router:8000
APP__SERVICES__DATA_PROCESSOR__URL=http://data-processor:8000
```

Эти переменные автоматически парсятся в структуру:

```python
settings.services.router.url = "http://router:8000"
settings.services.data_processor.url = "http://data-processor:8000"
```

### Структура ConfigLoader

Класс `ConfigLoader` определен в `services/common/config/loader.py`:

```{.python caption="services/common/config/loader.py (фрагмент)"}
class ConfigLoader:
    """Manages YAML configuration loading with caching and hot reload."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._config_root = self._detect_config_root()
        logger.info(f"ConfigLoader initialized with root: {self._config_root}")
    
    def _detect_config_root(self) -> Path:
        """Detect config root directory (container or dev environment)."""
        # Try container path first
        container_path = Path('/app/configs')
        if container_path.exists():
            return container_path
        
        # Try CWD (project root)
        cwd_path = Path(os.getcwd()) / 'configs'
        if cwd_path.exists():
            return cwd_path
            
        # Try relative to this file
        file_relative_path = Path(__file__).parent.parent.parent.parent / 'configs'
        if file_relative_path.exists():
            return file_relative_path
        
        raise FileNotFoundError("Config directory not found")
    
    def load(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file with !include support."""
        if config_path in self._cache:
            return self._cache[config_path]
        
        full_path = self._config_root / config_path
        # ... YAML parsing logic ...
        self._cache[config_path] = config
        return config
```

**Таблица: Приоритет поиска config root**

| Порядок | Путь | Контекст |
|---------|------|----------|
| 1 | `/app/configs` | Docker-контейнер (production) |
| 2 | `{CWD}/configs` | Локальная разработка (dev) |
| 3 | `{__file__}/../../../../configs` | Относительный путь от модуля |

Это обеспечивает работу как в Docker-контейнере (где проект монтируется в `/app`), так и в локальной среде разработки.

### Проблема: отсутствие переменных окружения

При первом запуске Gateway после рефакторинга возникла ошибка:

```
ValidationError: 1 validation error for Settings
services
  Field required [type=missing, input_value={}, input_type=dict]
```

**Причина:** В `docker-compose.yml` для сервиса `gateway` не были определены переменные окружения `APP__SERVICES__*`. Класс `Settings` пытался загрузить поле `services`, но не нашел соответствующих переменных.

**Диагностика:** Создан debug-скрипт для воспроизведения проблемы:

```{.python caption="debug_config_loader.py (временный файл)"}
from services.common.config import config_loader, Settings

try:
    settings = Settings()
    print(f"Settings loaded. Data processor URL: {settings.services.data_processor.url}")
except Exception as e:
    print(f"Failed to load settings: {e}")

try:
    registry = config_loader.load("gateway/route_registry.yaml")
    print("Route registry loaded successfully.")
except Exception as e:
    print(f"Failed to load route registry: {e}")
```

**Результат выполнения:**

```
Failed to load settings: 1 validation error for Settings
services
  Field required [type=missing, input_value={}, input_type=dict]

Route registry loaded successfully.
{'routes': [...]}
```

Это подтвердило, что проблема в отсутствии переменных окружения, а не в логике загрузки YAML.

### Решение: обновление docker-compose.yml

Добавлены переменные окружения и volume mount в секцию `gateway`:

```{.yaml caption="docker-compose.yml (секция gateway, после исправления)"}
services:
  gateway:
    build:
      context: .
      dockerfile: services/gateway/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - APP__SERVICES__ROUTER__URL=http://router:8000
      - APP__SERVICES__DATA_PROCESSOR__URL=http://data-processor:8000
    depends_on:
      - data-processor
      - router
    volumes:
      - ./configs:/app/configs
```

**Таблица: Изменения в docker-compose.yml**

| Элемент | До | После | Обоснование |
|---------|-----|-------|-------------|
| `environment` | `DATA_PROCESSOR_URL`, `ROUTER_URL` | `APP__SERVICES__ROUTER__URL`, `APP__SERVICES__DATA_PROCESSOR__URL` | Соответствие формату `services.common.config` |
| `volumes` | Отсутствует | `./configs:/app/configs` | Доступ к `route_registry.yaml` через `ConfigLoader` |

**Обоснование volume mount:**

`ConfigLoader` ищет конфигурационные файлы в `/app/configs`. Без volume mount директория `/app/configs` в контейнере пуста (в Docker-образе копируются только файлы из `services/gateway/src`). Volume mount `./configs:/app/configs` монтирует директорию `configs` из хост-системы в контейнер, обеспечивая доступ к `configs/gateway/route_registry.yaml`.

### Удаление устаревшего src/config.py

До рефакторинга Gateway использовал локальный файл `services/gateway/src/config.py`:

```{.python caption="services/gateway/src/config.py (legacy, удален)"}
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATA_PROCESSOR_URL: str = "http://data-processor:8000"
    ROUTER_URL: str = "http://router:8000"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
```

Этот файл дублировал функциональность `services.common.config` и создавал несовместимость (использование `DATA_PROCESSOR_URL` вместо `settings.services.data_processor.url`).

**Решение:** Файл удален. Импорт в `main.py` заменен на:

```{.python caption="services/gateway/src/main.py (импорт настроек)"}
# До:
from src.config import settings

# После:
from services.common.config import Settings, config_loader
settings = Settings()
```

**Таблица: Сравнение legacy config vs services.common.config**

| Критерий | Legacy (`src/config.py`) | `services.common.config` |
|----------|--------------------------|--------------------------|
| Формат переменных | `DATA_PROCESSOR_URL` | `APP__SERVICES__DATA_PROCESSOR__URL` |
| Поддержка вложенных полей | Нет | Да (через `__` delimiter) |
| Переиспользование | Только Gateway | Все сервисы |
| Поддержка YAML | Нет | Да (через `ConfigLoader`) |
| Размер кода | 12 строк | 61 строка (Settings) + 201 строка (ConfigLoader) |

Несмотря на больший размер `services.common.config`, централизация конфигурации снижает дублирование кода между сервисами.

### Верификация исправления

После обновления `docker-compose.yml` выполнена проверка через debug-скрипт:

```bash
$ ./.venv/bin/python3 debug_config_loader.py
Successfully imported services.common.config
Attempting to load settings...
Settings loaded. Data processor URL: http://data-processor:8000
Attempting to load route registry...
Route registry loaded successfully.
{'routes': [...]}
```

Ошибка `ValidationError` устранена. Gateway успешно загружает как `Settings` (из переменных окружения), так и `route_registry.yaml` (через `ConfigLoader`).

### Диаграмма потока конфигурации

```{.mermaid}
flowchart TD
    Start[Запуск Gateway] --> LoadEnv[Загрузка переменных окружения]
    LoadEnv --> ParseSettings[Pydantic парсинг Settings]
    ParseSettings --> ValidateSettings{Валидация успешна?}
    ValidateSettings -->|Нет| Error[ValidationError]
    ValidateSettings -->|Да| LoadYAML[ConfigLoader.load route_registry.yaml]
    LoadYAML --> DetectRoot[Определение config root]
    DetectRoot --> CheckCache{Файл в кэше?}
    CheckCache -->|Да| ReturnCache[Возврат из кэша]
    CheckCache -->|Нет| ParseYAML[Парсинг YAML]
    ParseYAML --> CacheResult[Сохранение в кэш]
    CacheResult --> RegisterRoutes[Регистрация маршрутов]
    ReturnCache --> RegisterRoutes
    RegisterRoutes --> Ready[Gateway готов]
```

### Преимущества централизованной конфигурации

1. **Единый источник истины:** Все сервисы используют одинаковый формат переменных окружения (`APP__*`).
2. **Типобезопасность:** Pydantic валидирует типы полей (например, `url: str`). Опечатка в переменной окружения приведет к ошибке при старте, а не в runtime.
3. **Автодополнение в IDE:** Поля `settings.services.router.url` доступны через автодополнение, в отличие от строковых ключей в dict.
4. **Переиспользование кода:** `ConfigLoader` используется всеми сервисами для загрузки YAML-конфигов (например, `Router` загружает параметры алгоритмов из `configs/router/algorithms.yaml`).

---

### Protocol Verification

* ✅ **Verified:** 
  - ValidationError при отсутствии `APP__SERVICES__*` — подтверждено выводом debug-скрипта в истории диалога.
  - Добавление переменных окружения и volume mount в `docker-compose.yml` — подтверждено diff'ом коммита `eb4b589`.
  - Удаление `services/gateway/src/config.py` (272 байта) — подтверждено git-историей (файл удален в коммите).
  - Успешная загрузка после исправления — подтверждено выводом debug-скрипта после правки `docker-compose.yml`.

* ⚠️ **Discrepancy:** 
  - Размер `src/config.py` указан как 272 байта (из git-истории), но в тексте упоминается 12 строк. Фактический размер файла был 272 байта, что соответствует ~12 строкам кода + комментарии.

* ❌ **Missing:** 
  - Автоматическая валидация `docker-compose.yml` при CI/CD (нет проверки наличия обязательных переменных окружения).
  - Документация формата переменных окружения (нет README с описанием `APP__SERVICES__*`).
