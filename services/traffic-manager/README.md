# Traffic Manager Service

**Phase 5** of multi-agent navigation system.

## Responsibilities

- **Edge Load Tracking**: Receives updates from Simulation Service
- **Congestion Calculation**: congestion = current_load / capacity
- **Redis Cache**: Fast access for routing (<5ms)
- **Hotspot Detection**: Top N most congested edges

## Architecture

```
Simulation Service → Traffic Manager (Redis cache) → Router/Coordinator
```

## API

### Get Congestion Stats
```bash
GET /api/v1/congestion/stats

Response:
{
  "total_edges": 50000,
  "congested_edges": 1500,
  "avg_congestion": 0.45,
  "max_congestion": 1.8
}
```

### Get Edge Congestion
```bash
POST /api/v1/congestion/edges
{
  "edge_ids": [1, 2, 3]
}

Response:
{
  "congestion": {
    "1": 0.75,
    "2": 1.2,
    "3": 0.3
  }
}
```

### Get Hotspots
```bash
GET /api/v1/congestion/hotspots?limit=10

Response:
{
  "hotspots": [
    [1234, 1.85],
    [5678, 1.72],
    ...
  ]
}
```

## Performance

- **Redis Cache Hit Rate**: >90%
- **Lookup Time**: <5ms per edge
- **Cache TTL**: 5 seconds
- **Update Frequency**: Every 1 second (from Simulation)

## Configuration

```yaml
database:
  host: localhost
  port: 5432
  name: osm
  
redis:
  host: localhost
  port: 6379
  ttl_sec: 5
  
congestion:
  threshold: 0.8
```

## Development

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8004
```

## Docker

```bash
docker build -t traffic-manager:latest .
docker run -p 8004:8004 traffic-manager:latest
```
