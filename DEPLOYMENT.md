# Запуск мультиагентной навигационной системы (новая архитектура)

## Предварительные требования

- Docker + Docker Compose
- 8 GB RAM минимум
- PostgreSQL data (osm graph) - загрузить через Data Processor

## Быстрый старт

### 1. Запуск инфраструктуры (PostgreSQL + Redis)

```bash
docker compose up -d postgis redis
```

Ждем health check (10-20 секунд):
```bash
docker compose ps
```

Должно быть `healthy` для postgis и redis.

### 2. Применение миграций

```bash
docker compose exec postgis psql -U postgres -d osm -f /docker-entrypoint-initdb.d/010_simulation_functions.sql
docker compose exec postgis psql -U postgres -d osm -f /docker-entrypoint-initdb.d/011_router_functions.sql
```

### 3. Загрузка graph data (опционально)

Если есть OSM data:
```bash
docker compose up -d data-processor
# Используйте API для загрузки: POST /api/v1/data/fetch
```

### 4. Запуск всех сервисов

```bash
docker compose up -d
```

Проверка статуса:
```bash
docker compose ps
docker compose logs -f simulation
docker compose logs -f coordinator
```

### 5. Health checks

```bash
curl http://localhost:8001/health  # Simulation
curl http://localhost:8002/health  # Coordinator
curl http://localhost:8003/health  # Router
curl http://localhost:8004/health  # Traffic Manager
curl http://localhost:8005/health  # Data Processor
```

## Архитектура сервисов

### Core Services

- **Simulation** (8001): Agent movement, tick loop @ 20 FPS
- **Coordinator** (8002): Routing orchestration, WebSocket hub
- **Router** (8003): K-shortest paths (pgRouting + diversity)
- **Traffic Manager** (8004): Congestion tracking (Redis cache)
- **Data Processor** (8005): OSM data fetching, graph building

### Monitoring

- **Grafana** (3000): Dashboards (admin/admin)
- **Loki** (3100): Log aggregation
- **Promtail**: Log shipping from all services

### Legacy (compatibility)

- **Server** (8000): Old monolithic server (for OSM tiles)
- **Client**: PyQt6 GUI (optional)

## API Examples

### Create Agent

```bash
# Через Coordinator (рекомендуется)
curl -X POST http://localhost:8002/api/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "start_lat": 55.7558,
    "start_lon": 37.6173,
    "end_lat": 55.7522,
    "end_lon": 37.6156,
    "route_edge_ids": [1, 2, 3],
    "priority": 0,
    "agent_type": "car_normal"
  }'

# Напрямую в Simulation (для тестирования)
curl -X POST http://localhost:8001/simulation/agents \
  -H "Content-Type: application/json" \
  -d '{
    "route_edge_ids": [1, 2, 3],
    "start_lat": 55.7558,
    "start_lon": 37.6173,
    "agent_type": "car_normal"
  }'
```

### Get Agent Position

```bash
curl http://localhost:8001/simulation/agents/{agent_id}/position
```

### Start Simulation

```bash
curl -X POST http://localhost:8001/simulation/start
```

### WebSocket (GUI positions)

```javascript
const ws = new WebSocket('ws://localhost:8002/ws/positions');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data.positions);  // Array of agent positions
};
```

## Configuration

### Environment Variables

Все сервисы используют:
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Coordinator дополнительно: `SIMULATION_URL`, `ROUTER_URL`, `TRAFFIC_URL`
- Traffic Manager дополнительно: `REDIS_HOST`, `REDIS_PORT`

### YAML Configs

- `configs/simulation/simulation.yaml` - FPS, BPR parameters, sync intervals
- `configs/simulation/agent_physics.yaml` - agent types, physics

## Troubleshooting

### Simulation не стартует

```bash
docker compose logs simulation
# Проверить:
# 1. PostgreSQL доступен (POSTGRES_HOST)
# 2. Таблица graphs.edges существует
# 3. SQL функция graphs.get_simulation_graph() создана
```

### Coordinator не получает позиции

```bash
docker compose logs coordinator
# Проверить:
# 1. Simulation Service запущен (http://simulation:8001/health)
# 2. Есть агенты в симуляции
# 3. WebSocket clients подключены
```

### Router SQL ошибки

```bash
docker compose exec postgis psql -U postgres -d osm
\df graphs.*  # Проверить функции
SELECT * FROM graphs.edges LIMIT 10;  # Проверить данные
```

## Development

### Hot reload (for changes)

```bash
docker compose watch simulation  # Auto-sync code changes
```

### Logs

```bash
docker compose logs -f --tail=100 simulation coordinator router
```

### Grafana Dashboards

1. Open http://localhost:3000
2. Login: admin/admin
3. Add Loki datasource: http://loki:3100
4. Create dashboard with queries:
   - `{container="simulation"}` - Simulation logs
   - `{container="coordinator"}` - Coordinator logs

## Testing

### Integration Test Flow

1. Start all services
2. Create agent via Coordinator
3. Start simulation
4. Check positions via WebSocket
5. Verify DB sync (agents table updates)

### Load Test

```bash
# Create 100 agents
for i in {1..100}; do
  curl -X POST http://localhost:8002/api/v1/agents \
    -H "Content-Type: application/json" \
    -d '{"start_lat": 55.75, "start_lon": 37.61, "end_lat": 55.76, "end_lon": 37.62, "route_edge_ids": [1,2,3]}'
done

# Start simulation
curl -X POST http://localhost:8001/simulation/start

# Monitor performance
docker stats
```

## Cleanup

```bash
# Stop all
docker compose down

# Remove volumes (data loss!)
docker compose down -v

# Remove old backups
rm -rf .trash/architecture-pre-15-11-2025/
```

## Next Steps

1. **Load graph data** - use Data Processor to fetch OSM and build graph
2. **Test K-routes** - verify Router Service with real graph
3. **GUI integration** - connect PyQt6 client to Coordinator WebSocket
4. **Baseline testing** - compare with/without rerouting
5. **Production optimization** - tune FPS, sync intervals, Redis TTL
