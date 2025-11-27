# Router Service

**Pluggable K-shortest paths routing service** with support for multiple algorithms (A*, pgRouting).

## Features

- **Pluggable Algorithms**: Easy switch between A* and pgRouting via config
- **K-Diverse Routes**: Multiple alternative routes with diversity enforcement
- **Turn Penalties**: Two-level turn cost system (routing + agent physics)
- **Agent Modes**: normal, hurry, cautious, emergency (with speed multipliers)
- **Priority Handling**: Emergency agents (priority ≥20) ignore congestion
- **Snap to Road**: PostGIS-based edge snapping for start/end points
- **Country-specific Speed Limits**: Configurable defaults per country
- **Comprehensive Logging**: Trace/debug/info logs to file (router.log)

## Architecture

```
services/router/
├── src/
│   ├── main.py           # FastAPI app
│   ├── manager.py        # RouterManager (config loader, engine factory)
│   ├── engine.py         # RouteEngine ABC interface
│   ├── astar_engine.py   # A* + Yen implementation (uses src/routing/)
│   └── models.py         # API models (RouteRequest, RouteResponse)
├── Dockerfile
└── requirements.txt
```

### Engine Interface

```python
class RouteEngine(ABC):
    async def initialize()
    async def shutdown()
    async def calculate_routes(
        start_lat, start_lon, end_lat, end_lon,
        k=3, agent_mode="normal", priority=0
    ) -> List[Route]
    async def snap_to_road(lat, lon, k=5) -> List[Tuple[int, float]]
```

### Implementations

- **AStarEngine**: Custom Python A* + Yen (uses `src/routing/pathfinding.py`)
- **PgRoutingEngine** (TODO): SQL-based pgRouting calls

## Configuration

**File**: `configs/router.yaml`

```yaml
# Algorithm selection
algorithm: astar  # or 'pgrouting'

# Routing parameters
routing:
  default_k: 3
  max_k: 10
  diversity:
    penalty_factor: 1.5
    threshold: 0.3
    similarity_threshold: 0.75
  snap:
    k_nearest: 5
    max_distance_m: 100.0

# Turn penalties (two-level)
turn_penalties:
  enabled: true
  routing:
    straight: 0.0   # 0-30°
    slight: 2.5     # 30-60°
    medium: 7.5     # 60-120°
    sharp: 15.0     # 120-150°
    uturn: 20.0     # 150-180°
    uturn_oneway: inf
  physics:
    max_acceleration: 2.0
    max_deceleration: 3.0
    turn_speed_factors:
      straight: 1.0
      slight: 0.9
      medium: 0.7
      sharp: 0.5
      uturn: 0.3

# Agent modes
agent_modes:
  normal:
    speed_multiplier: 1.0
  hurry:
    speed_multiplier: 1.2
  emergency:
    speed_multiplier: 1.5
    ignore_congestion: true
    priority: 100

# Speed limits
speed_limits:
  use_db: true
  country_defaults:
    RU:
      motorway: 110
      primary: 90
      residential: 40
```

## API Endpoints

### POST /api/v1/routes

Calculate K alternative routes.

**Request**:
```json
{
  "start_lat": 55.751244,
  "start_lon": 37.617779,
  "end_lat": 55.754321,
  "end_lon": 37.623456,
  "k": 3,
  "agent_type": "normal",
  "priority": 0
}
```

**Response**:
```json
{
  "routes": [
    {
      "route_id": 0,
      "segments": [...],
      "total_distance_m": 5234.5,
      "estimated_time_sec": 412.3,
      "diversity_score": 0.0,
      "edge_ids": [1234, 5678, ...]
    }
  ]
}
```

### GET /health

Health check.

**Response**:
```json
{
  "status": "healthy",
  "service": "router",
  "algorithm": "astar"
}
```

## Usage

### Docker Compose

```bash
# Build
docker compose build router

# Start
docker compose up -d router

# Logs
docker compose logs -f router

# Check health
curl http://localhost:8003/health

# Calculate routes
curl -X POST http://localhost:8003/api/v1/routes \
  -H "Content-Type: application/json" \
  -d '{
    "start_lat": 55.751244,
    "start_lon": 37.617779,
    "end_lat": 55.754321,
    "end_lon": 37.623456,
    "k": 3
  }'
```

### Development

```bash
# Install dependencies
pip install -r services/router/requirements.txt

# Run locally
uvicorn services.router.src.main:app --reload --port 8003
```

## Logging

- **Console**: INFO level (colored)
- **File**: `logs/router.log` (DEBUG level, rotated at 10 MB, 7 days retention)

**Log levels**:
- `TRACE`: Detailed intermediate steps (snapping, path segments)
- `DEBUG`: Algorithm execution details (k-shortest paths, diversity)
- `INFO`: High-level operations (route calculation start/end)
- `WARNING`: Missing data, fallbacks
- `ERROR`: Failures, exceptions

## Performance

### AStarEngine (src/routing/)

- **Graph loading**: ~500ms (PostgreSQL → memory)
- **Point snapping**: ~5-10ms per point (Euclidean)
- **A* pathfinding**: ~20-50ms per path
- **K-shortest paths (Yen)**: ~100-200ms for k=5
- **Total latency**: ~600-700ms (cold start + routing)

**Optimizations**:
- Graph cached in memory (load once at startup)
- Adjacency list for O(1) neighbor access
- PostGIS ST_Distance for snapping (TODO: ~1-2ms with GIST index)

## Future Enhancements

1. **PgRoutingEngine**: SQL-based implementation using pgRouting extension
2. **Route Caching**: Cache routes by (start, end, k) key (TTL 5 min)
3. **Parallel Snapping**: ProcessPool for multiple snap points
4. **Graph Updates**: Hot-reload graph on DB changes (WebSocket notification)
5. **Metrics**: Prometheus metrics (routing_time_ms, cache_hit_rate)

## Dependencies

- **FastAPI**: Web framework
- **asyncpg**: PostgreSQL async driver (for future pgRouting)
- **psycopg2-binary**: PostgreSQL sync driver (for src/routing/)
- **pyyaml**: Config loading
- **loguru**: Structured logging
- **src/routing/**: Custom A* + Yen implementation (graph.py, pathfinding.py)

## Testing

```bash
# Run tests
pytest services/router/tests/

# Test specific endpoint
curl -X POST http://localhost:8003/api/v1/routes \
  -H "Content-Type: application/json" \
  -d @services/router/tests/fixtures/request.json
```

## References

- **Algorithm**: Yen's K-Shortest Paths (https://en.wikipedia.org/wiki/Yen%27s_algorithm)
- **Turn Penalties**: Two-level system (final.instruction.md)
- **Agent Modes**: Speed multipliers and behavior (configs/router.yaml)
- **Diversity**: Shared edges penalty + similarity threshold
