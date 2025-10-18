# Архитектурные принципы и дизайн (актуально)

Этот документ фиксирует принципы и конкретные решения, на которых строится проект МАС-навигации.

## Базовые принципы
- SOLID и «чистая архитектура»: разделение на слои Data → Domain → Application → Presentation.
- Зависимость от абстракций (интерфейсов), а не конкретных реализаций.
- Плагинообразность ключевых компонентов: движок маршрутизации, источник дорожных данных, симулятор.
- Наблюдаемость: структурированные логи, метрики, трассировки — с R-D-2.

## Целевая архитектура (высокоуровнево)

- Координатор (Server as source of truth): FastAPI
	- REST: /route, /graph, служебные.
	- WS: поток позиций/событий (R-D-2).
	- Интеграции: PostGIS (граф дорог), Valhalla (основной роутер), Redis (Streams/PubSub), SUMO (симуляция — опционально).

- Клиент (GUI): PyQt + QWebEngineView + MapLibre GL JS
	- Лёгкий мост Python↔JS: runJavaScript (R-D-1), QWebChannel (R-D-2).
	- Слои: base tiles, graph, routes, agents, overlays (closures/heat).
	- Сохранение настроек: QSettings + YAML.

- Данные/обработка:
	- PostGIS: хранение edges/nodes, ограничения, аудит изменений.
	- Redis: Streams — ingest телеметрии; Pub/Sub — рассылка в WS; кэши маршрутов/стоимостей (TTL).
	- Valhalla: основной движок маршрутизации с live-traffic (traffic tiles).

## Паттерны и подходы

- CQRS: канал записи (телеметрия/изменения графа) отделён от канала чтения (маршруты/позиции для клиентов).
- Event-driven: позиции и события поступают как события в стримы; обновления скоростей/закрытий батчатся; координация с гистерезисом.
- Адаптивный пере-роутинг: координатор триггерит пересчёт планов по порогам деградации ETA.
- Edge-ID mapping: сохраняем соответствие PostGIS edge_id ↔ Valhalla edge_id при сборке тайлов.

## Интерфейсы (контракты)

```python
class RouteEngine(Protocol):
		def route(self, waypoints: list[tuple[float, float]], profile: str = "auto") -> dict: ...

class TrafficProvider(Protocol):
		def update_edge_speeds(self, speeds: dict[int, float]) -> None: ...
		def close_edges(self, edge_ids: list[int]) -> None: ...

class TelemetrySink(Protocol):
		def push_positions(self, batch: list[dict]) -> None: ...
```

Реализации: `ValhallaRouteEngine`, `PostgisPgRoutingEngine` (утилитарно), `RedisTrafficProvider`, `RedisStreamsSink`.

## Обработка ошибок и устойчивость

- Доменные исключения: RouteNotFound, GraphDisconnected, TrafficUpdateFailed.
- Валидация входных данных (pydantic) на уровне API.
- Повторы и backoff для вызовов внешних сервисов (Valhalla, Redis, Postgres).
- Circuit breaker для деградирующих интеграций.

## Производительность и масштабирование

- Валхалла масштабируется горизонтально; шардирование по регионам.
- Redis — один инстанс на dev, кластер на prod; применять keyspace-дизайн и TTL.
- PostGIS — индексы GIST/BTREE, матвью для тяжёлых отчётов.
- Клиент: WebGL-рендер, агрегация и дросселирование WS-апдейтов.

## Тестирование

- Unit: преобразование геоданных, маршрутизация на toy-графах, сериализация GeoJSON.
- Интеграция: REST/WS контракты; Redis pub/sub roundtrip; pgRouting/Valhalla smoketests.
- E2E: сценарии с 1–N агентами; сравнение KPI (ETA, пропускная способность) в двух режимах (наивный vs координированный).
