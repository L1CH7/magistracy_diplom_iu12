# Teleportation Debugging Guide

## Быстрый старт

### 1. Проверка телепортации в реальном времени

```bash
# Показать только телепортации (live)
python scripts/view_logs.py --teleportations --follow

# Показать ошибки (включая телепортации)
python scripts/view_logs.py --errors --follow
```

### 2. Анализ после воспроизведения

```bash
# Показать все телепортации за сессию
python scripts/view_logs.py --teleportations --tail 100

# Показать движение конкретного агента
python scripts/view_logs.py --agent 1 --trace --tail 200
```

### 3. Включение детального трейсинга

```python
# В начале src/client/main.py или src/server/main.py
from src.utils.loguru_config import enable_trace_logging
enable_trace_logging()  # Логирует КАЖДОЕ движение агента
```

## Уровни логирования

### TRACE (детальное отслеживание)
```python
logger.trace("agent_position_calc", agent_id=1, lon=37.6, lat=55.7)
logger.trace("agent_position_result", distance_traveled_m=1234.5)
logger.trace("agent_movement_ok", distance_m=5.2, threshold_m=10.0)
```

**Когда использовать**: При активном поиске причины телепортации. Логирует КАЖДЫЙ кадр движения.

**Zero-cost**: Если TRACE отключен (по умолчанию), код НЕ выполняется.

### ERROR (телепортация обнаружена)
```python
log.error("🚨 TELEPORTATION_DETECTED 🚨",
    distance_m=1500.0,
    threshold_m=10.0,
    teleport_ratio=150.0
)
```

**Когда**: Телепортация ОБНАРУЖЕНА. Критичная ошибка.

## Формула детектирования

```
dS_critical = v_max * dt
dt = sim_speed / fps
v_max = 200 km/h = 55.56 m/s

threshold = dS_critical * 1.1  (10% запас)

if distance_between_frames > threshold:
    TELEPORTATION!
```

Пример:
- sim_speed = 30x
- fps = 60
- dt = 30/60 = 0.5 сек (реального времени)
- dS_critical = 55.56 * 0.5 = 27.78 м
- threshold = 27.78 * 1.1 = 30.56 м

Если агент переместился на **> 30.56 м** за кадр → **ТЕЛЕПОРТАЦИЯ**.

## Сценарии отладки

### Сценарий 1: "Агент телепортируется при смене маршрута"

**Симптомы**:
```
🚨 TELEPORTATION_DETECTED 🚨
distance_m: 1500.0
threshold_m: 30.56
agent_state: {"route_id": 42, "state": "Moving"}
```

**Как дебажить**:
1. Включить TRACE:
   ```python
   from src.utils.loguru_config import enable_trace_logging
   enable_trace_logging()
   ```

2. Воспроизвести:
   ```bash
   # Запустить агента
   # Сменить маршрут
   # Дождаться телепортации
   ```

3. Проверить логи:
   ```bash
   python scripts/view_logs.py --agent 1 --trace --tail 500
   ```

4. Искать в логах:
   - `agent_rerouted_success` - момент смены маршрута
   - `agent_position_calc` ДО и ПОСЛЕ смены
   - `TELEPORTATION_DETECTED` - где произошла телепортация

5. Проверить:
   - Корректно ли пересчитан `start_time` при смене маршрута?
   - Совпадают ли координаты OLD route с NEW route в момент переключения?

### Сценарий 2: "Агент телепортируется на старте"

**Симптомы**:
```
🚨 TELEPORTATION_DETECTED 🚨
prev_pos: null
current_pos: [37.6, 55.7]
```

**Причина**: `_prev_position` = None на первом кадре.

**Решение**: В `_check_teleportation` пропускаем первый кадр:
```python
if self._prev_position is None:
    self._prev_position = current_pos
    return  # Skip first frame
```

### Сценарий 3: "Агент телепортируется при merge routes"

**Симптомы**:
```
auto_switch_merged_route: merged_edges=50
TELEPORTATION_DETECTED: distance_m=2000.0
```

**Как дебажить**:
1. Проверить логи merge:
   ```bash
   python scripts/view_logs.py --function "merge" --tail 100
   ```

2. Найти:
   - `merge_distance_check` - расчет расстояний
   - `distance_to_edge_start` - где начинается current edge в merged route
   - `adjusted_sim_time` - пересчет start_time

3. Проверить:
   - Правильно ли рассчитано `distance_to_edge_start`?
   - Учтены ли все edges от начала merged route до current edge?
   - Корректен ли `adjusted_sim_time = distance / v_max`?

## Графana Loki Queries

Если Grafana доступна (http://localhost:3000):

### Все телепортации
```logql
{job="app_logs"} |= "TELEPORTATION_DETECTED"
```

### Телепортации по агенту
```logql
{job="app_logs"} | json | agent_id="1" |= "TELEPORTATION"
```

### Движение агента (TRACE)
```logql
{job="app_logs"} | json | level="TRACE" | agent_id="1"
```

### График: Teleportations per minute
```logql
rate({job="app_logs"} |= "TELEPORTATION_DETECTED" [1m])
```

### График: Agent distance jumps
```logql
{job="app_logs"} | json | message="agent_position_result" 
  | unwrap distance_traveled_m
```

## Советы по debugging

### 1. Используйте TRACE осторожно
TRACE логирует КАЖДЫЙ кадр (60 FPS = 60 логов/сек).
**Включайте только при активном debugging!**

### 2. Проверяйте start_time
При ЛЮБОМ изменении маршрута проверьте:
```python
logger.info("start_time_check",
    agent_id=agent.agent_id,
    start_time=agent.start_time,
    current_time=time.time(),
    elapsed=time.time() - agent.start_time
)
```

### 3. Логируйте distance calculations
```python
logger.debug("distance_calc",
    distance_traveled=distance_traveled,
    sim_time=sim_time,
    max_speed=agent.params.max_speed,
    route_distance=route_distance_m
)
```

### 4. Проверяйте route consistency
```python
logger.info("route_edges_check",
    old_edges_count=len(old_route['edges']),
    new_edges_count=len(new_route['edges']),
    current_edge_in_old=current_edge_id in old_route['edges'],
    current_edge_in_new=current_edge_id in new_route['edges']
)
```

## Checklist при обнаружении телепортации

- [ ] Воспроизведена ли телепортация стабильно?
- [ ] Включен ли TRACE для детального логирования?
- [ ] Проверены ли логи с `--agent <ID> --trace`?
- [ ] Найден ли moment смены маршрута (`agent_rerouted_success`)?
- [ ] Корректен ли `start_time` после смены?
- [ ] Совпадают ли координаты в момент переключения?
- [ ] Проверен ли расчет `distance_to_edge_start` в merge?
- [ ] Сохранены ли логи для дальнейшего анализа?

## Полезные команды

```bash
# Смотреть телепортации в реальном времени
python scripts/view_logs.py --teleportations --follow

# Смотреть движение агента 1 (TRACE)
python scripts/view_logs.py --agent 1 --trace --follow

# Последние 100 ошибок
python scripts/view_logs.py --errors --tail 100

# Все логи функции get_current_position
python scripts/view_logs.py --function get_current_position --tail 200

# Медленные операции
python scripts/view_logs.py --slow --tail 50

# Полный вывод с всеми полями
python scripts/view_logs.py --teleportations --full
```

## Структура логов

### app.jsonl
Все логи приложения (TRACE, DEBUG, INFO, WARNING, ERROR).

### errors.jsonl
Только ERROR и CRITICAL (включая телепортации).

### slow_operations.jsonl
Операции длительностью > 1 секунды.

## Контакты для AI Agent

Если ты (AI агент) обнаружил телепортацию:

1. **Включи TRACE**:
   ```python
   from src.utils.loguru_config import enable_trace_logging
   enable_trace_logging()
   ```

2. **Воспроизведи ошибку**

3. **Собери логи**:
   ```bash
   python scripts/view_logs.py --agent <ID> --trace --tail 1000 > debug.log
   ```

4. **Анализируй** debug.log:
   - Найди `TELEPORTATION_DETECTED`
   - Найди предшествующие `agent_position_result`
   - Найди `agent_rerouted_success` или `auto_switch_merged_route`
   - Проверь `start_time`, `distance_traveled`, `progress`

5. **Создай issue** с:
   - Логами (debug.log)
   - Описанием сценария
   - Гипотезой причины
   - Предложением фикса

Удачи! 🚀
