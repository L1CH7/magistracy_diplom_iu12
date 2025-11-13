# Logging Quick Start для AI Agent

## 🚀 Быстрый старт (3 команды)

### 1. Смотреть телепортации в реальном времени
```bash
python scripts/view_logs.py --teleportations --follow
```

### 2. Если телепортация обнаружена - включить TRACE
```bash
python scripts/enable_trace.py both
docker-compose restart client server
```

### 3. Собрать детальные логи для анализа
```bash
python scripts/view_logs.py --agent 1 --trace --tail 500 > teleport_debug.log
```

## 📊 Основные команды

| Команда | Описание |
|---------|----------|
| `python scripts/view_logs.py --errors --follow` | Live errors |
| `python scripts/view_logs.py --teleportations` | Все телепортации |
| `python scripts/view_logs.py --agent 1 --trace` | Движение агента 1 |
| `python scripts/view_logs.py --function get_current_position` | Логи функции |
| `python scripts/enable_trace.py status` | Проверить TRACE статус |
| `python scripts/enable_trace.py both` | Включить TRACE везде |

## 🎯 Сценарии использования

### Сценарий 1: Обычная разработка (без телепортации)

```bash
# Запустить приложение
docker-compose up -d

# Смотреть общие логи
python scripts/view_logs.py --tail 50

# Смотреть только ошибки
python scripts/view_logs.py --errors
```

**TRACE отключен** → zero CPU overhead

### Сценарий 2: Телепортация обнаружена

```bash
# 1. Увидели телепортацию в логах
python scripts/view_logs.py --teleportations
# 🚨 TELEPORTATION_DETECTED distance_m=1500.0

# 2. Включить TRACE для детального трейсинга
python scripts/enable_trace.py both
docker-compose restart client server

# 3. Воспроизвести проблему

# 4. Собрать детальные логи
python scripts/view_logs.py --agent 1 --trace --tail 1000 > debug.log

# 5. Анализировать debug.log (см. docs/TELEPORTATION_DEBUG.md)
```

### Сценарий 3: Отладка конкретной функции

```bash
# Включить TRACE только на сервере
python scripts/enable_trace.py server
docker-compose restart server

# Смотреть логи конкретной функции
python scripts/view_logs.py --function merge_routes --trace --follow
```

### Сценарий 4: Live monitoring

```bash
# Terminal 1: Ошибки
python scripts/view_logs.py --errors --follow

# Terminal 2: Телепортации
python scripts/view_logs.py --teleportations --follow

# Terminal 3: Движение агента
python scripts/view_logs.py --agent 1 --trace --follow
```

## 🔧 Управление TRACE

### Включить TRACE

```bash
# Оба контейнера
python scripts/enable_trace.py both

# Только клиент
python scripts/enable_trace.py client

# Только сервер
python scripts/enable_trace.py server
```

### Проверить статус

```bash
python scripts/enable_trace.py status
```

Output:
```
📊 TRACE Status:
────────────────────────────────────────
client    : 🟢 ENABLED
server    : ⚫ DISABLED
────────────────────────────────────────
```

### Отключить TRACE

```bash
python scripts/enable_trace.py disable both
docker-compose restart client server
```

## 📁 Структура логов

```
.agent_dir/logs/
├── app.jsonl              # Все логи (TRACE, DEBUG, INFO, WARNING, ERROR)
├── errors.jsonl           # Только ERROR и CRITICAL
├── slow_operations.jsonl  # Операции > 1 секунды
├── TRACE_ENABLED_client   # Flag file (если TRACE включен)
└── TRACE_ENABLED_server   # Flag file (если TRACE включен)
```

## 🔍 Типичные логи

### Normal movement (TRACE)
```json
{
  "level": "TRACE",
  "message": "agent_movement_ok",
  "agent_id": 1,
  "distance_m": 5.2,
  "threshold_m": 30.56,
  "from_pos": [37.6, 55.7],
  "to_pos": [37.60001, 55.70001]
}
```

### Teleportation (ERROR)
```json
{
  "level": "ERROR",
  "message": "🚨 TELEPORTATION_DETECTED 🚨",
  "agent_id": 1,
  "distance_m": 1500.0,
  "threshold_m": 30.56,
  "teleport_ratio": 49.08,
  "agent_state": {
    "speed_kmh": 50.0,
    "route_id": 42,
    "state": "Moving"
  }
}
```

### Position calculation (TRACE)
```json
{
  "level": "TRACE",
  "message": "agent_position_result",
  "agent_id": 1,
  "lon": 37.6,
  "lat": 55.7,
  "bearing": 90.0,
  "speed_mps": 13.89,
  "edge_id": 123,
  "progress": 0.45,
  "distance_traveled_m": 1234.5
}
```

## ⚠️ Важно

### TRACE - это много логов!
- 60 FPS × 2 логa (calc + result) = **120 логов/сек/агент**
- Файлы растут быстро: **~10MB/минута** при TRACE
- **Используй TRACE только при активной отладке!**

### Zero-Cost гарантия
- Если TRACE отключен (по умолчанию) → **ZERO CPU overhead**
- Строки не форматируются, функции не вызываются
- Можно оставить `logger.trace()` в коде навсегда

### Ротация логов
- Автоматическая ротация при 500MB (app.jsonl)
- Compression: старые логи архивируются в .zip
- Retention: хранятся 7 дней

## 🎓 Дополнительная документация

- **docs/LOGGING.md** - Полная документация по логированию
- **docs/TELEPORTATION_DEBUG.md** - Отладка телепортации (подробно)
- **docs/INSTRUMENTATION.md** - Автоматическая инструментация функций
- **.github/agent_logging_guide.md** - Оригинальный гайд

## 🆘 Troubleshooting

### Логи не появляются
```bash
# Проверить что директория существует
ls -lah .agent_dir/logs/

# Проверить что контейнеры запущены
docker-compose ps

# Проверить логи контейнера
docker-compose logs client | tail -20
```

### TRACE не работает после включения
```bash
# 1. Проверить flag file
python scripts/enable_trace.py status

# 2. Перезапустить контейнеры
docker-compose restart client server

# 3. Проверить что TRACE действительно пишется
python scripts/view_logs.py --trace --tail 10
```

### Слишком много логов
```bash
# Отключить TRACE
python scripts/enable_trace.py disable both
docker-compose restart client server

# Удалить старые логи
rm .agent_dir/logs/app.jsonl
```

## 💡 Tips для AI Agent

1. **Всегда начинай с --errors**
   ```bash
   python scripts/view_logs.py --errors --tail 50
   ```

2. **Используй --follow для live debugging**
   ```bash
   python scripts/view_logs.py --teleportations --follow
   ```

3. **Включай TRACE только когда нужно**
   ```bash
   python scripts/enable_trace.py both
   # Reproduce bug
   python scripts/enable_trace.py disable both
   ```

4. **Сохраняй логи для анализа**
   ```bash
   python scripts/view_logs.py --agent 1 --trace > debug_$(date +%Y%m%d_%H%M%S).log
   ```

5. **Фильтруй по функциям**
   ```bash
   python scripts/view_logs.py --function get_current_position --trace
   ```

Удачи в отладке! 🚀
