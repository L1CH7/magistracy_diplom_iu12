# TODO - 14 декабря 2025

## Завершенные задачи из предыдущего TODO (09-12-25)

### ✅ Priority 1 - Архитектура
- [x] **ROUTER_URL** - исправлено (8003 → 8006)
- [x] **snap_to_road column name** - исправлено (geometry → geom)
- [x] **pgr_KSP type casting** - исправлено (added ::bigint, ::integer)
- [x] **Diversity filter** - настроено (0.4 → 0.65, сделан параметром)

### ✅ Priority 2 - Качество роутинга
- [x] **Geometry zigzag fix** - маршруты теперь корректно ориентированы (backward edges)
- [x] **Node sequence tracking** - добавлено в Route dataclass
- [x] **Turn restrictions validation** - фикс null constraint violation

### ✅ Критичный фикс - Connectivity
- [x] **Graph fragmentation** - исправлено увеличением ST_DWithin tolerance (2m → 5m)
  * Было: 226,545 компонентов на moscow_mkad
  * Стало: Граф связный на moscow_center (44k ways)

---

## Текущие проблемы (Приоритет 1)

### 1. Multi-point routing не поддерживается ❌
**Проблема**: Клиент может отправить только start/end, но не waypoints  
**Требование**: Добавить поддержку промежуточных точек маршрута

**План**:
- [ ] Проверить API coordinator - принимает ли waypoints?
- [ ] Если нет - добавить в RouteRequest model
- [ ] Реализовать цепочку роутингов: start→wp1→wp2→...→end
- [ ] Склеить результаты в единый маршрут
- [ ] Тесты с 3-5 waypoints

**Файлы**:
- `services/coordinator/src/models.py` - RouteRequest
- `services/coordinator/src/manager.py` - routing logic
- `services/router/src/api/routing.py` - может потребоваться batch API

---

### 2. Роутинг игнорирует мосты/тоннели ⚠️
**Проблема**: Делает повороты там где физически нельзя (разные уровни дорог)  
**Причина**: OSM теги `layer`, `bridge`, `tunnel` не учитываются

**План**:
- [ ] Добавить колонки в graphs.edges: `layer INTEGER`, `is_bridge BOOLEAN`, `is_tunnel BOOLEAN`
- [ ] Обновить graph_builder для извлечения этих тегов из OSM
- [ ] Модифицировать логику split_ways_into_edges:
  * Не создавать intersection node если ways на разных layer
  * Пример: bridge (layer=1) пересекает road (layer=0) → НЕ создавать узел пересечения
- [ ] Проверить что turn_restrictions учитывают layer

**Примечание**: Полное решение требует quality check OSM данных (не все мосты/тоннели правильно отмаркированы)

**Файлы**:
- `services/router/src/graph/graph_builder.py` - find_and_create_intersection_nodes()
- `migrations/` - ADD COLUMN layer, is_bridge, is_tunnel
- Тесты на реальных данных (найти мосты в moscow_center)

---

### 3. Клиент зависает при запросе маршрута 🔴
**Симптомы**: UI freezes, no response  
**Гипотезы**:
1. Coordinator timeout слишком большой
2. Нет индикатора загрузки в UI
3. Routing запрос блокирует main thread

**План**:
- [ ] Добавить loading indicator в GUI перед запросом
- [ ] Проверить timeout settings:
  * Client → Coordinator timeout
  * Coordinator → Router timeout
- [ ] Логировать время каждого этапа (snap, pgr_KSP, geometry fetch)
- [ ] Если router зависает на pgr_KSP > 5s → добавить timeout + fallback
- [ ] Проверить нет ли deadlock в async code

**Файлы**:
- `src/client/ui/main_window.py` - добавить loading spinner
- `src/client/handlers/api_handler.py` - timeout settings
- `services/coordinator/src/manager.py` - timeout propagation
- Логи router: искать долгие запросы

---

## Метрики и мониторинг (Приоритет 2)

### 4. Добавить метрики времени ⏱️
**Требование**: Видеть performance в реальном времени

**Метрики для сбора**:
1. **Graph build time**:
   - Total time
   - Time per stage (intersection nodes, split edges, barriers, restrictions)
   - Nodes/edges count
   - Ways count (input)

2. **OSM download time**:
   - Time per tile
   - Ways downloaded per tile
   - Overpass server used
   - Failures/retries

3. **Routing time** (самое важное):
   - snap_to_edge time (per point)
   - pgr_KSP time
   - geometry_fetch time
   - diversity_filter time
   - Total time (end-to-end)
   - Success rate (found routes / total requests)

**План**:
- [ ] Добавить timing decorators в router
- [ ] Создать `/api/v1/metrics` endpoint (Prometheus format)
- [ ] Настроить Grafana dashboard:
  * Routing latency (p50, p95, p99)
  * Success rate
  * Graph size over time
- [ ] Логировать slow queries (pgr_KSP > 1s)

**Файлы**:
- `services/router/src/utils/metrics.py` (создать)
- `services/router/src/api/routing.py` - добавить @track_time
- `services/router/src/graph/graph_builder.py` - track each stage
- `configs/grafana/routing_dashboard.json` (создать)

---

## Логирование (Приоритет 2)

### 5. Переработать логирование router 📝
**Проблемы**:
1. Спам каждые 100 узлов (при 1M узлов = 10k логов!)
2. Нет уровня TRACE для debug
3. Некоторые этапы не логируют прогресс
4. Огромный спам "Graph node not found near OSM node"

**План**:
- [ ] Добавить уровень TRACE (отключен по умолчанию)
- [ ] Уменьшить частоту прогресс-логов:
  * <1000 items: каждые 100 (10%)
  * 1k-10k: каждые 1000 (10%)
  * >10k: каждые 10000 (1%)
- [ ] Спам "Graph node not found": логировать summary в конце, не каждый случай
- [ ] Добавить progress bar вместо логов для длинных операций
- [ ] Структурировать логи по этапам:
  ```
  [GRAPH BUILD] Starting...
  [GRAPH BUILD] [1/6] Intersection nodes: 10% (12000/120000)
  [GRAPH BUILD] [1/6] Complete: 120000 nodes in 23s
  ```

**Файлы**:
- `services/router/src/graph/graph_builder.py` - весь файл
- `src/utils/loguru_config.py` - добавить TRACE level
- Проверить router-latest.log (10k строк)

---

## UX улучшения (Приоритет 3)

### 6. Унифицировать процесс построения графа 🔧
**Проблема**: Неудобный workflow:
1. Очистить БД вручную
2. Дернуть `/tiles/redownload`
3. Дождаться загрузки
4. Дернуть `/graph/rebuild`
5. Дождаться построения

**Требование**: Единый конвейер одной командой

**План**:
- [ ] Создать endpoint `POST /api/v1/workflow/rebuild_full`:
  ```json
  {
    "bbox": {"min_lon": ..., "max_lon": ...},
    "clear_existing": true,
    "build_graph": true
  }
  ```
- [ ] Логика:
  1. Truncate OSM tables (если clear_existing=true)
  2. Download OSM data (tiles/redownload)
  3. Wait for download complete (poll tasks)
  4. Trigger graph rebuild
  5. Return statistics
- [ ] Добавить WebSocket прогресс:
  * Download progress: 45% (tile 23/51)
  * Graph build: 60% (splitting ways)
- [ ] CLI wrapper script для удобства:
  ```bash
  ./scripts/rebuild_graph.sh moscow_center
  ```

**Файлы**:
- `services/coordinator/src/api/workflow.py` (создать)
- `scripts/rebuild_graph.sh` (создать)
- GUI кнопка "Reload Region" с выбором bbox

---

## Проверка turn_restrictions (Приоритет 2)

### 7. Убедиться что turn restrictions работают ✔️
**Текущее состояние**:
- Restrictions загружаются в `graphs.turn_restrictions`
- НО: pgr_KSP их НЕ использует!

**План**:
- [ ] Изучить pgRouting docs:
  * pgr_trsp - поддерживает turn restrictions
  * pgr_withPointsKSP - тоже?
- [ ] Реализовать интеграцию:
  ```sql
  SELECT * FROM pgr_trsp(
    'SELECT id, source, target, cost, reverse_cost FROM graphs.edges',
    'SELECT to_cost, target_id, via_path FROM graphs.turn_restrictions',
    start_node, end_node, directed:=true
  )
  ```
- [ ] Тесты:
  * Найти место с no_left_turn restriction
  * Проверить что маршрут его обходит
  * Сравнить с/без restrictions
- [ ] Fallback если restrictions ломают роутинг:
  * Попробовать с restrictions
  * Если 0 paths → retry без restrictions + warning

**Файлы**:
- `services/router/src/engine/pgrouting_engine.py` - заменить pgr_KSP на pgr_trsp
- Тесты с реальными данными

---

## Следующие шаги (Порядок выполнения)

1. **Сейчас**: Проверить turn_restrictions (пункт 7) - критично для качества
2. **Срочно**: Фикс клиент зависает (пункт 3) - UX blocker
3. **Важно**: Multi-point routing (пункт 1) - функциональность
4. **Потом**: Метрики (пункт 4) - visibility
5. **Потом**: Логирование (пункт 5) - maintenance
6. **Потом**: Унификация workflow (пункт 6) - convenience
7. **Опционально**: Мосты/тоннели (пункт 2) - требует качественных OSM данных

---

## Архивировано (выполнено ранее)

### Из TODO_ROUTING_IMPROVEMENTS.md (09-12-25):
- ✅ ROUTER_URL fix (8003→8006)
- ✅ snap_to_road column rename (geometry→geom)
- ✅ pgr_KSP type casting
- ✅ Diversity filter (настроен, параметризован)
- ✅ Geometry zigzag fix (coordinate reversal для backward edges)
- ✅ Node sequence tracking (добавлено в Route)
- ✅ Turn restrictions validation (null constraint fix)
- ✅ Graph connectivity catastrophe (ST_DWithin tolerance 2m→5m)

### Не выполнено (перенесено в этот TODO):
- ⏳ Централизация API endpoints → отложено, не критично сейчас
- ⏳ Snap logic improvements → работает, но требует улучшений (отложено)
- ⏳ K routes count fix → diversity filter работает, но не всегда возвращает k маршрутов
- ⏳ Grafana metrics → перенесено в пункт 4
- ⏳ Turn restrictions integration → перенесено в пункт 7
- ⏳ Cost function improvements → отложено (требует BPR traffic model)

---

## Технические долги

1. **Performance**: Graph build на moscow_mkad занимает 3 часа
   - Решение: Batch processing, параллелизация
   - Приоритет: Low (moscow_center достаточно для тестов)

2. **Testing**: Нет regression tests для роутинга
   - Решение: Создать test suite с фиксированными OD pairs
   - Приоритет: Medium

3. **Documentation**: README устарел
   - Решение: Обновить после стабилизации API
   - Приоритет: Low

4. **API versioning**: Нет версионирования endpoints
   - Решение: Пока не критично (monolith deployment)
   - Приоритет: Low
