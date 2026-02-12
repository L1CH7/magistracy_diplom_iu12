# Конфигурация и сборка

## Введение

Система конфигурации построена на YAML-файлах с поддержкой включений (`!include`) и переменных окружения. Конфигурация загружается через общий модуль `config_loader` (используется всеми сервисами) и валидируется через Pydantic Settings.

Сборка автоматизирована через Makefile, который управляет виртуальным окружением, зависимостями и компиляцией переводов.

## Система конфигурации

### Структура конфигурационных файлов

```
configs/client/
├── map.yaml           # Конфигурация карты (LOD, стили, анимация)
├── map.lod.yaml       # LOD-слои (включается в map.yaml)
├── map.rendering.yaml # Стили рендеринга (цвета, ширины)
├── network.yaml       # URL Gateway, таймауты
├── data.yaml          # Таймауты API, лимиты отображения
└── gui.yaml           # Настройки UI (локаль, debug mode)
```

### Загрузчик конфигурации

`config_loader` — общий модуль для всех сервисов, обеспечивающий:
- Загрузку YAML с поддержкой `!include`.
- Резолюцию переменных окружения.
- Кеширование загруженных файлов.

```{.python caption="services/common/config/config_loader.py (концептуально)"}
class ConfigLoader:
    """Unified config loader for all services."""
    
    def __init__(self, config_root: str):
        self.config_root = config_root
        self._cache = {}
    
    def load(self, config_path: str) -> dict:
        """Load config file with !include support."""
        if config_path in self._cache:
            return self._cache[config_path]
        
        full_path = os.path.join(self.config_root, config_path)
        
        with open(full_path, 'r') as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        
        self._cache[config_path] = config
        return config
```

### Пример: Конфигурация карты

```{.yaml caption="configs/client/map.yaml"}
# LOD (Level of Detail) layers
lod: !include map.lod.yaml

# Rendering configuration
rendering: !include map.rendering.yaml

# Initial map view settings
initial:
  center: [37.6173, 55.7558]  # Moscow center [lon, lat]
  zoom: 12
  minZoom: 0
  maxZoom: 19

# Animation parameters
animation:
  agentSmoothing: 0.25  # Lerp alpha for agent movement
  maxFrameDelta: 0.05   # Max seconds per animation frame
  zoomDuration: 200     # Milliseconds

# Tile configuration
tiles:
  tileSize: 256
  defaultUrl: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
```

### Инъекция в JavaScript

Конфигурация передаётся в JavaScript через `ConfigBridge`:

```{.python caption="handlers/config_bridge.py"}
@pyqtSlot(result=str)
def getMapConfig(self) -> str:
    """Return map config as JSON string."""
    if self._map_config is None:
        self._map_config = config_loader.load('client/map.yaml')
    
    # Inject apiBaseUrl from GUI config
    if 'apiBaseUrl' in self._config:
        self._map_config['apiBaseUrl'] = self._config['apiBaseUrl']
        
    return json.dumps(self._map_config)
```

## Управление зависимостями

### requirements.txt

```{.txt caption="services/qt-client/requirements.txt"}
loguru
pydantic
pydantic-settings
PyQt5
PyQtWebEngine
pyyaml
pyyaml-include
qt5-tools
requests
websockets
httpx
```

**Ключевые зависимости:**
- `PyQt5` — UI-фреймворк.
- `PyQtWebEngine` — Chromium-движок для WebView.
- `pyyaml-include` — Поддержка `!include` в YAML.
- `websockets` — WebSocket-клиент.
- `httpx` — Асинхронный HTTP-клиент.

### Виртуальное окружение

Используется Python 3.13 с изолированным venv:

```{.bash caption="Создание venv"}
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Makefile: Автоматизация сборки

### Структура Makefile

```{.makefile caption="services/qt-client/Makefile"}
# Variables
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
PYTHON   := $(VENV_BIN)/python
PIP      := $(VENV_BIN)/pip
PYLUPDATE := $(VENV_BIN)/pylupdate5

# Source Files
UI_SOURCES := $(shell find ui -name "*.py")
TS_FILES := $(shell find translations -name "*.ts")

# Targets
.PHONY: all setup install translate compile clean run

# Default target
all: install compile

# 1. Environment Setup
$(VENV_DIR):
	@echo ">>> Creating virtual environment..."
	python3.13 -m venv $(VENV_DIR)

install: $(VENV_DIR)
	@echo ">>> Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ">>> Environment ready."

# 2. Translation Workflow
update-ts: install
	@echo ">>> Generating/Updating translation files (.ts)..."
	$(PYLUPDATE) $(UI_SOURCES) -ts $(TS_FILES)
	@echo "✅ .ts files updated. Now edit them manually."

compile: install
	@echo ">>> Compiling binary translations (.qm)..."
	$(eval LRELEASE := $(shell find $(VENV_DIR) -type f -name lrelease | head -n 1))
	@if [ -z "$(LRELEASE)" ]; then \
		echo "❌ Error: 'lrelease' not found in $(VENV_DIR)."; \
		exit 1; \
	fi; \
	echo "🔧 Using lrelease at: $(LRELEASE)"; \
	$(LRELEASE) translations/*.ts
	@echo "✅ .qm files compiled successfully."

# 3. Helpers
clean:
	@echo ">>> Cleaning up..."
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f translations/*.qm

run: 
	@echo ">>> Starting Application..."
	$(PYTHON) main.py
```

### Использование

```{.bash caption="Команды Makefile"}
# Установка зависимостей
make install

# Обновление .ts файлов (после изменения кода)
make update-ts

# Компиляция переводов
make compile

# Запуск приложения
make run

# Очистка
make clean
```

## Компиляция переводов

### Процесс локализации

1. **Извлечение строк:**
   ```bash
   make update-ts
   ```
   `pylupdate5` сканирует Python-код и обновляет `.ts` файлы.

2. **Перевод:**
   Редактирование `translations/app_ru.ts` в Qt Linguist.

3. **Компиляция:**
   ```bash
   make compile
   ```
   `lrelease` компилирует `.ts` → `.qm`.

4. **Загрузка:**
   Приложение загружает `.qm` при старте через `QTranslator`.

### Пример .ts файла

```{.xml caption="translations/app_ru.ts (фрагмент)"}
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="ru_RU">
<context>
    <name>PointsPanel</name>
    <message>
        <source>Route Points</source>
        <translation>Точки маршрута</translation>
    </message>
    <message>
        <source>Get Route</source>
        <translation>Построить маршрут</translation>
    </message>
</context>
</TS>
```

## Переменные окружения

**Таблица: Переменные окружения**

| Переменная | Назначение | Значение по умолчанию |
|------------|-----------|----------------------|
| `GATEWAY_URL` | URL Gateway | `http://localhost:8000` |
| `QT_QPA_PLATFORMTHEME` | Отключение системной темы | `` (пусто) |
| `QT_STYLE_OVERRIDE` | Принудительный стиль Qt | `Fusion` |
| `QTWEBENGINE_REMOTE_DEBUGGING_PORT` | Порт для remote debugging | `9222` |

### Использование

```{.bash caption="Запуск с переменными окружения"}
GATEWAY_URL=http://gateway:8000 make run
```

## Выводы

Система конфигурации и сборки обеспечила:
- **Гибкость:** YAML с `!include` позволяет разделять конфигурацию на модули.
- **Переиспользование:** `config_loader` используется всеми сервисами.
- **Автоматизацию:** Makefile упрощает сборку и компиляцию переводов.
- **Изоляцию:** Виртуальное окружение предотвращает конфликты зависимостей.

**Компромиссы:**
- **Сложность:** Makefile требует знания GNU Make.
- **Зависимость от qt5-tools:** `lrelease` находится глубоко в site-packages, требуется динамический поиск.

**Метрики:**
- Количество конфигурационных файлов: 5.
- Размер зависимостей (venv): ~500 МБ.
- Время установки зависимостей: ~2 минуты.

---

## Приложение: Схема конфигурации

```{.mermaid}
graph TB
    subgraph "Configuration Files"
        MapYAML[map.yaml]
        LODYAML[map.lod.yaml]
        RenderYAML[map.rendering.yaml]
        NetYAML[network.yaml]
        DataYAML[data.yaml]
    end
    
    subgraph "Python"
        ConfigLoader[config_loader]
        ConfigBridge[ConfigBridge]
    end
    
    subgraph "JavaScript"
        MapConfig[map-config-loader.js]
    end
    
    MapYAML -->|!include| LODYAML
    MapYAML -->|!include| RenderYAML
    
    MapYAML --> ConfigLoader
    NetYAML --> ConfigLoader
    DataYAML --> ConfigLoader
    
    ConfigLoader --> ConfigBridge
    ConfigBridge -->|JSON| MapConfig
    
    style ConfigLoader fill:#3b82f6,color:#fff
    style ConfigBridge fill:#22c55e,color:#fff
```
