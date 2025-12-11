# Routing Improvements TODO

## Priority 1 (Critical) - Архитектура

### Централизация API endpoints через сервер
**Проблема**: Множество эндпоинтов разбросаны по разным портам, нет единой точки входа
**Текущее**: 
- Client → http://localhost:8002 (coordinator)
- Client → http://localhost:8000 (legacy server для OSM fetch)
- Direct service calls in docker-compose

**Требование**: Централизованное проксирование через единый сервер
```
Client → Server:8000/some/operation
         ↓
         Coordinator:8002/api/v1/some/operation
         Router:8006/api/v1/some/operation
         Data-Processor:8005/api/v1/some/operation
```

**План**:
1. [ ] Создать API Gateway Service (nginx/FastAPI)
2. [ ] Переписать маршрутизацию: `GET/POST server:port/operation → service:port/api/v1/operation`
3. [ ] Обновить client endpoints для использования gateway
4. [ ] Добавить мониторинг запросов через gateway
5. [ ] Документировать единую точку входа в README

**Файлы для изменения**:
- `docker-compose.yml` - добавить api-gateway service
- `src/client/services/*_client.py` - обновить base_url
- `src/client/ui/main_window_handlers.py` - обновить прямые вызовы
- Создать `services/api-gateway/` с nginx конфигом или FastAPI прокси

## Priority 2 (High) - Качество роутинга

### Проблема: Через раз нет маршрутов (snap_to_edge чудит)
**Симптомы**:
- pgr_KSP возвращает 0 paths → "No routes found from node X to node Y"
- Яндекс Навигатор находит маршруты в тех же точках
- snap_to_edge ведёт "не туда" - выбирает неправильные узлы

**Гипотезы**:
1. **Snap радиус слишком мал** (текущий 500m)
2. **Выбор ближайшего узла неоптимален**:
   ```python
   # Текущая логика:
   if position_m < edge_info['length_m'] / 2:
       node_id = edge_info['source']
   else:
       node_id = edge_info['target']
   ```
   - Не учитывает направление движения
   - Не учитывает oneway дороги
   - Не учитывает связность компонентов графа

3. **Граф имеет несвязанные компоненты** (residential/service дороги изолированы)

**План**:
1. [ ] Добавить логирование snap decisions: `(lat,lon) → edge X → node Y (reason: ...)`
2. [ ] Реализовать проверку связности компонентов перед роутингом
3. [ ] Улучшить выбор узла: учитывать bearing, oneway, node degree
4. [ ] Добавить fallback: если pgr_KSP вернул 0 paths → увеличить snap_radius → retry
5. [ ] Добавить pre-check перед snap: есть ли путь в радиусе 1km (использовать component_id)
6. [ ] Добавить A* fallback если pgr_KSP не находит маршруты

**Файлы**:
- `services/router/src/engine/pgrouting_engine.py` - улучшить snap_to_node()
- `services/router/src/api/routing.py` - добавить component check, fallback логику
- `migrations/` - добавить component_id в graphs.nodes

### Проблема: Не возвращает запрошенное количество маршрутов
**Симптомы**: 
- Client запрашивает k=5
- Coordinator/Router возвращает только 2

**Причина**: Diversity filter слишком строгий
- Overlap threshold 65% отсекает слишком много маршрутов
- pgr_KSP возвращает 6 paths, но 4 из них rejected (overlap > 0.65)

**План**:
1. [ ] Сделать diversity_threshold настраиваемым параметром (default 0.65)
2. [ ] Если найдено < k маршрутов → ослабить threshold до 0.75 → retry
3. [ ] Добавить опцию disable_diversity для тестирования
4. [ ] Логировать overlap values для анализа
5. [ ] Рассмотреть альтернативные метрики diversity (не только edge overlap):
   - Time difference
   - Highway type diversity
   - Geometric distance (area between routes)

**Файлы**:
- `services/router/src/engine/pgrouting_engine.py` - параметризовать threshold
- `services/router/src/api/routing.py` - добавить diversity_threshold в RouteRequest
- `services/coordinator/src/manager.py` - передавать threshold от клиента

## Priority 3 (Medium) - Улучшения

### 1. Добавить turn restrictions в роутинг
**Текущее**: Turn restrictions есть в БД (`graphs.turn_restrictions`), но pgr_KSP не использует
**План**:
- [ ] Изучить pgr_trsp / pgr_withPointsKSP для turn restrictions
- [ ] Интегрировать в PgRoutingEngine
- [ ] Сравнить качество маршрутов до/после

### 2. Улучшить cost функцию
**Текущее**: `cost = length_m / effective_speed_kmh` (simple)
**Нужно учитывать**:
- Traffic lights count
- Turns count (penalty за повороты)
- Highway priority (prefer trunk > secondary)
- Current traffic load (BPR function уже есть)

### 3. Оптимизация производительности
**Текущее**: 2 маршрута за ~110ms (приемлемо)
**Можно улучшить**:
- [ ] Кэшировать частые OD пары (Redis)
- [ ] Предварительно вычислять top-N маршрутов для популярных направлений
- [ ] Использовать CH (Contraction Hierarchies) для ускорения

### 4. Grafana метрики
**TODO (помечено в коде)**:
```python
# TODO: Log to Grafana
# await log_routing_metrics(
#     computation_time_ms=elapsed_ms,
#     num_routes=len(route_responses),
#     total_edges=sum(len(r.edge_ids) for r in route_responses)
# )
```
- [ ] Реализовать отправку метрик в Prometheus/Grafana
- [ ] Добавить дашборд с routing statistics

## Тестирование

### Добавить тесты для routing
- [ ] Unit tests для PgRoutingEngine (mock DB)
- [ ] Integration tests для routing API
- [ ] Performance tests (target: <200ms для 5 маршрутов)
- [ ] Regression tests для проблемных точек (где Yandex находит, а мы нет)

### Добавить визуализацию для debugging
- [ ] Endpoint для экспорта snap points (debug mode)
- [ ] GUI кнопка "Show snap candidates" (показать top-5 nearest edges)
- [ ] Highlight component boundaries на карте (где граф не связан)

## Документация

- [ ] Обновить README с новым API routing
- [ ] Задокументировать централизованную архитектуру endpoints
- [ ] Добавить troubleshooting guide для "No route found"
- [ ] Добавить performance benchmarks в docs/

---

## Известные Issues (из коммита)

1. ✅ **ROUTER_URL** - исправлено (8003 → 8006)
2. ✅ **snap_to_road column name** - исправлено (geometry → geom)
3. ✅ **pgr_KSP type casting** - исправлено (added ::bigint, ::integer)
4. ✅ **Diversity filter** - настроено (0.4 → 0.65)
5. ⚠️ **Snap logic** - работает, но требует улучшений (Priority 2)
6. ⚠️ **k routes count** - возвращает меньше чем запрошено (Priority 2)

## Следующие шаги

1. **Срочно**: Централизация API endpoints (Priority 1)
2. **Важно**: Фикс snap logic + connectivity checks (Priority 2)
3. **Потом**: Grafana metrics, turn restrictions (Priority 3)
