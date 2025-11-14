# Simulation Service

FastAPI service managing agent movement simulation.

## Features

- **Batch simulation**: Uses numpy vectorization for 1000+ agents
- **20 FPS tick rate**: Real-time movement updates
- **Dynamic agents**: Add/remove agents at runtime
- **Route updates**: Switch routes on-the-fly
- **GPU support**: Optional CuPy acceleration

## Architecture

```
SimulationManager
├── AgentBatch (numpy arrays)
├── GraphCache (edge data)
├── ConfigManager (YAML configs)
└── Tick Loop (async @ 20 FPS)
    ├── move_batch() - vectorized movement
    ├── detect_teleports() - validation
    └── broadcast_positions() - to Coordinator
```

## API Endpoints

### Control
- `POST /simulation/start` - Start simulation loop
- `POST /simulation/stop` - Stop simulation
- `GET /simulation/status` - Get status (fps, agent_count, etc)

### Agents
- `POST /simulation/agents` - Add agent
  ```json
  {
    "route_edge_ids": [1, 2, 3],
    "start_lat": 55.751244,
    "start_lon": 37.618423,
    "agent_type": "car_normal",
    "config_overrides": {"max_speed_override_kmh": 80}
  }
  ```
  
- `DELETE /simulation/agents/{agent_id}` - Remove agent
- `PUT /simulation/agents/{agent_id}/route` - Update route
  ```json
  {"route_edge_ids": [4, 5, 6]}
  ```
  
- `GET /simulation/agents/{agent_id}` - Get agent state
- `GET /simulation/agents` - List all agents

### Health
- `GET /health` - Health check

## Running

### Local
```bash
cd services/simulation
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

### Docker
```bash
docker build -t simulation-service .
docker run -p 8001:8001 simulation-service
```

### Docker with GPU
```bash
docker run --gpus all -p 8001:8001 simulation-service
```

## Configuration

Agent configs in `configs/simulation/agent_physics.yaml`:
- Agent types: car_normal, car_hurry, emergency, truck
- Physics: acceleration zones, turn penalties
- Regional speed margins: РФ +19 km/h, Турция +10%

## Performance

Target: < 5ms per tick for 1000 agents
- CPU: ~3-5ms (Numba JIT)
- GPU: ~1-2ms (CuPy)

## Integration

### With Coordinator
- Coordinator calls `/simulation/agents` to add agents
- Coordinator calls `/simulation/agents/{id}/route` to update routes
- Simulation broadcasts positions via WebSocket (TODO)

### With Database
- Loads GraphCache from PostgreSQL+PostGIS (TODO)
- Edge speeds, geometries, turn angles

## Development

### Testing
```bash
pytest tests/
```

### Linting
```bash
ruff check src/
```

## TODO

- [ ] Load GraphCache from database
- [ ] Implement WebSocket broadcast to Coordinator
- [ ] Implement teleport detection alerts
- [ ] Add Prometheus metrics
- [ ] Add health check dependencies (database connection)
