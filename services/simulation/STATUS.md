# Simulation Service

## Status: ✅ COMPLETE (structure ready, needs testing)

## Created Files

### Core Service
- [x] `src/main.py` - FastAPI application (234 lines)
- [x] `src/manager.py` - SimulationManager class (419 lines)
- [x] `src/models.py` - Pydantic models (56 lines)
- [x] `src/__init__.py` - Package exports (19 lines)

### Configuration
- [x] `requirements.txt` - Python dependencies
- [x] `requirements-dev.txt` - Test dependencies
- [x] `Dockerfile` - Docker container config
- [x] `pyproject.toml` - Pytest configuration

### Documentation
- [x] `README.md` - Service documentation with API reference

### Tests
- [x] `tests/test_manager.py` - SimulationManager unit tests (251 lines)
- [x] `tests/test_api.py` - FastAPI integration tests (209 lines)

## Architecture

```
services/simulation/
├── src/
│   ├── __init__.py          # Package exports
│   ├── main.py              # FastAPI app + endpoints
│   ├── manager.py           # SimulationManager (core logic)
│   └── models.py            # Pydantic models
├── tests/
│   ├── test_manager.py      # Unit tests
│   └── test_api.py          # API integration tests
├── Dockerfile               # Container
├── requirements.txt         # Dependencies
├── requirements-dev.txt     # Dev dependencies
├── pyproject.toml           # Pytest config
└── README.md                # Documentation
```

## Key Features

### SimulationManager
- **AgentBatch management**: Add/remove agents dynamically
- **Tick loop**: 20 FPS async loop
- **Vectorized movement**: Uses `move_batch()` from Phase 1
- **Route updates**: Switch routes on-the-fly
- **Status monitoring**: Real-time stats

### API
- RESTful endpoints for all operations
- Pydantic validation
- Error handling with proper HTTP codes
- Health checks

### Performance
- Numpy vectorization for agent updates
- Target: < 5ms per tick for 1000 agents
- GPU support (optional, via move_batch)

## Integration Points

### With Phase 1 (Agent System)
- Uses `AgentBatch` from `src/shared/agent/movement_batch.py`
- Uses `move_batch()` for vectorized updates
- Uses `AgentConfigManager` for configs

### With Coordinator (Phase 3 - TODO)
- Broadcasts positions via WebSocket/HTTP
- Receives add/remove/update commands via REST

### With Database (TODO)
- Load GraphCache from PostgreSQL+PostGIS
- Edge speeds, geometries, turn angles

## TODOs

1. **Graph Loading**:
   - [ ] Implement `_load_graph_cache()` in manager.py
   - [ ] Query PostgreSQL+PostGIS for edges
   - [ ] Build GraphCache with dense arrays

2. **Broadcasting**:
   - [ ] Implement `broadcast_positions()` in manager.py
   - [ ] WebSocket client to Coordinator
   - [ ] HTTP POST fallback

3. **Teleport Detection**:
   - [ ] Use `detect_teleports_batch()` in tick loop
   - [ ] Alert Coordinator on teleports
   - [ ] Log warnings

4. **Metrics**:
   - [ ] Add Prometheus metrics endpoint
   - [ ] Track: tick_duration, agent_count, fps

5. **Testing**:
   - [ ] Run unit tests (pytest tests/test_manager.py)
   - [ ] Run integration tests (pytest tests/test_api.py)
   - [ ] Load testing (1000 agents)

## Running

### Local Development
```bash
cd services/simulation
pip install -r requirements.txt -r requirements-dev.txt
uvicorn src.main:app --reload --port 8001
```

### Testing
```bash
pytest tests/ -v
```

### Docker
```bash
docker build -t simulation-service .
docker run -p 8001:8001 simulation-service
```

## Next Phase

**Phase 3: Coordinator Service**
- Create `services/coordinator/`
- Manage agent lifecycle
- Route calculation orchestration
- Rerouting logic
- WebSocket hub for GUI clients
