# Coordinator Service

**Phase 3** of multi-agent navigation system.

## Responsibilities

- **Route Calculation**: K alternative routes with diversity penalties
- **Agent Lifecycle**: Create/remove agents (orchestrates Simulation Service)
- **Rerouting**: Congestion-based rerouting (hybrid strategy)
- **WebSocket Hub**: Broadcast positions to GUI clients

## Architecture

```
GUI → Coordinator → Simulation Service
              ↓
          Router Service (Phase 4)
              ↓
          Traffic Manager (Phase 5)
```

## API

### Calculate Routes
```bash
POST /api/v1/routes/calculate
{
  "start_lat": 55.7558,
  "start_lon": 37.6173,
  "end_lat": 55.7522,
  "end_lon": 37.6156,
  "k": 3,
  "priority": 0,
  "agent_type": "car_normal"
}
```

### Create Agent
```bash
POST /api/v1/agents
{
  "start_lat": 55.7558,
  "start_lon": 37.6173,
  "end_lat": 55.7522,
  "end_lon": 37.6156,
  "route_edge_ids": [1, 2, 3],
  "priority": 0,
  "agent_type": "car_normal"
}
```

### Remove Agent
```bash
DELETE /api/v1/agents/{agent_id}
```

### Rerouting Status
```bash
GET /api/v1/rerouting/status
```

### WebSocket (GUI)
```javascript
ws://localhost:8002/ws/positions
```

## Configuration

TODO: Add config.yaml (rerouting strategy, thresholds, etc)

## Development

```bash
# Install deps
pip install -r requirements.txt

# Run
uvicorn src.main:app --reload --port 8002

# Docker
docker build -t coordinator:latest .
docker run -p 8002:8002 coordinator:latest
```

## Testing

```bash
pytest tests/
```

## Performance

- **Route Calculation**: <50ms @ K=3 (depends on pgRouting)
- **Agent Creation**: <10ms (HTTP call to Simulation)
- **Rerouting**: Check every 5 sec, <100ms per batch

## Next Steps (Phase 4)

1. Implement Router Service (pgRouting integration)
2. Create SQL function: graphs.get_k_routes_with_diversity()
3. Add tests
