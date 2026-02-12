# Технический отчет: API Gateway

## Аннотация

Данный отчет описывает рефакторинг модуля API Gateway для мультисервисной архитектуры навигационной системы. Система переведена с жестко закодированных маршрутов на динамическую регистрацию через декларативный реестр (`route_registry.yaml`). Ключевые достижения: централизованная конфигурация через `services.common.config`, устранение дублирования кода, поддержка двунаправленного WebSocket-проксирования для real-time обновлений карты.

**Ключевые компромиссы:** Отказ от встроенной аутентификации ради минимизации задержки (latency). Gateway выполняет роль легковесного прокси с базовой защитой через ограничение доступных эндпоинтов.

---

## Структура отчета

### [Глава 1: Архитектурный контекст и проблематика](./01_architecture_context.md)

**Содержание:**
- Роль Gateway в микросервисной архитектуре.
- Проблемы жестко закодированных маршрутов (hardcoded routes).
- Требования к производительности и безопасности.
- Обоснование выбора динамической регистрации.

**Ключевые выводы:**
- Hardcoded routes приводят к нарушению DRY и усложняют масштабирование.
- Централизованная конфигурация через YAML снижает риск ошибок при добавлении новых сервисов.
- Отказ от аутентификации обоснован требованием минимальной задержки (target: <50ms overhead).

---

### [Глава 2: Реализация динамической маршрутизации](./02_dynamic_routing.md)

**Содержание:**
- Структура `route_registry.yaml` (декларативное описание маршрутов).
- Алгоритм загрузки и регистрации маршрутов в FastAPI.
- Решение проблемы Loop Variable Capture через фабрику обработчиков.
- Интеграция с `services.common.config` для резолвинга URL сервисов.

**Ключевые метрики:**
- Удалено: 77 строк hardcoded routes.
- Добавлено: 30 строк декларативной конфигурации.
- Поддержка: 7 HTTP-методов (GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD).

---

### [Глава 3: HTTP и WebSocket проксирование](./03_proxy_implementation.md)

**Содержание:**
- Реализация `reverse_proxy`: streaming response, фильтрация заголовков.
- Обработка edge-case: HTTP 204 No Content (запрет chunked encoding).
- WebSocket проксирование: двунаправленная передача (bidirectional forwarding).
- Connection pooling через `httpx.AsyncClient` (20 keepalive, 100 max connections).

**Ключевые метрики:**
- Overhead проксирования: ~5-10 мс (HTTP), ~2 мс (WebSocket handshake).
- Timeout: 60 секунд (защита от зависших запросов).
- Обработка ошибок: HTTP 503 (upstream unavailable), HTTP 500 (proxy error).

---

### [Глава 4: Интеграция с общей конфигурацией](./04_config_integration.md)

**Содержание:**
- Архитектура `services.common.config`: Settings, ConfigLoader.
- Проблема: отсутствие переменных окружения в `docker-compose.yml`.
- Решение: добавление `APP__SERVICES__*` и volume mount `/app/configs`.
- Удаление устаревшего `src/config.py` (legacy settings).

**Ключевые изменения:**
- `docker-compose.yml`: добавлены `APP__SERVICES__ROUTER__URL`, `APP__SERVICES__DATA_PROCESSOR__URL`.
- `docker-compose.yml`: добавлен volume `./configs:/app/configs`.
- Удален файл: `services/gateway/src/config.py` (272 байта legacy кода).

---

### [Глава 5: Отладка и исправление ошибок](./05_debugging_fixes.md)

**Содержание:**
- Диагностика: ValidationError при загрузке Settings (missing `services` field).
- Воспроизведение проблемы через debug-скрипт.
- Исправление: IndentationError в `proxy.py` (неправильная вложенность блока).
- Верификация через `py_compile`.

**Ключевые метрики:**
- Время диагностики: ~3 минуты (от ошибки до root cause).
- Исправлено: 19 строк кода (de-indent блока response handling).

---

### [Глава 6: Выводы и планы развития](./06_conclusions.md)

**Содержание:**
- Технический долг (rate limiting, circuit breaker, distributed tracing).
- Расширение функциональности (аутентификация через JWT, метрики Prometheus).
- Границы применимости (когда Gateway подходит / не подходит).
- Честная самооценка (достижения и недостатки).

**Главный вывод:**
Gateway обеспечивает баланс между простотой и гибкостью. Отсутствие аутентификации — осознанный компромисс ради минимизации задержки. Архитектура готова к добавлению rate limiting и observability после интеграции с production-окружением.

---

## Технологический стек

**Таблица: Используемые технологии**

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| API Framework | FastAPI | 0.115.0 |
| ASGI Server | Uvicorn | 0.30.0 |
| HTTP Client | httpx | 0.27.0 |
| WebSocket Library | websockets | 12.0 |
| Config Management | Pydantic Settings | 2.2.0 |
| YAML Parser | PyYAML + pyyaml-include | 6.0.1 + 2.0 |
| Logging | Loguru | 0.7.2 |
| Язык | Python | 3.11 |
| Контейнеризация | Docker | 24.0 |

---

## Ключевые файлы кодовой базы

**Таблица: Структура проекта**

| Файл | Описание | Строк кода |
|------|----------|------------|
| `services/gateway/src/main.py` | Ядро Gateway (динамическая регистрация маршрутов, lifespan) | 133 |
| `services/gateway/src/proxy.py` | HTTP reverse proxy (streaming, header filtering) | 61 |
| `services/gateway/src/ws_proxy.py` | WebSocket bidirectional proxy | 50 |
| `configs/gateway/route_registry.yaml` | Декларативный реестр маршрутов | 30 |
| `services/common/config/settings.py` | Глобальная конфигурация (Settings, ServiceConfig) | 61 |
| `services/common/config/loader.py` | YAML loader с кэшированием и env expansion | 201 |
| `docker-compose.yml` | Конфигурация Gateway service (env vars, volumes) | 14 (секция gateway) |

---

## Контакты и ссылки

**Репозиторий:** `L1CH7/magistracy_diplom_iu12`  
**Ветка:** `features/R-D-1/architecture`  
**Коммит:** `eb4b589` (Refactor gateway to use dynamic routing registry)  
**Дата коммита:** 26.01.2026

---

## Приложения

### Приложение A: Пример конфигурации

**Route Registry (route_registry.yaml):**

```{.yaml caption="configs/gateway/route_registry.yaml"}
routes:
  - path: "/tiles"
    service: "data_processor"
    internal_prefix: "/api/v1/tiles"
  
  - path: "/routing"
    service: "router"
    internal_prefix: "/api/v1/routing"
```

**Environment Variables (docker-compose.yml):**

```{.yaml caption="docker-compose.yml (gateway service)"}
environment:
  - APP__SERVICES__ROUTER__URL=http://router:8000
  - APP__SERVICES__DATA_PROCESSOR__URL=http://data-processor:8000
volumes:
  - ./configs:/app/configs
```

### Приложение B: Диаграмма потока запроса

```{.mermaid}
sequenceDiagram
    participant Client
    participant Gateway
    participant ConfigLoader
    participant Router
    participant DataProcessor

    Client->>Gateway: GET /routing/calculate
    Gateway->>ConfigLoader: load("gateway/route_registry.yaml")
    ConfigLoader-->>Gateway: routes config
    Gateway->>Gateway: resolve service URL (router)
    Gateway->>Router: GET /api/v1/routing/calculate
    Router-->>Gateway: HTTP 200 + route data
    Gateway-->>Client: HTTP 200 + route data
```

---

**Дата создания отчета:** 05.02.2026  
**Версия:** 2.2 (следует промпту Antigravity Report Prompt 2.2)
