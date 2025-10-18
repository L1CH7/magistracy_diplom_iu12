# Navigation MAS

Server-coordinator + GUI client for navigation MAS project. Fetches OSM data, builds graphs, routes agents by time.

## Quick Start

### Local Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
# Server
uvicorn src.server.app:app --host 0.0.0.0 --port 8000
# Client (in another terminal)
python src/client/gui.py
```

### Docker Run
```bash
# Allow Docker to access X11 (Linux only)
xhost +local:docker

# Run services
docker-compose up --build

# After done, revoke access
xhost -local:docker
```

## Features
- OSM data fetching via Overpass API
- NetworkX graph building with time weights
- Dijkstra routing
- FastAPI server with /route, /agent/start/step, /osm/load
- Tkinter GUI client for route requests and agent simulation
- Docker containers for server and client

## Structure
- `src/server/app.py` — FastAPI server
- `src/client/gui.py` — Tkinter GUI
- `src/data/` — OSM loader and graph builder
- `src/routing/` — Simple routing engine
- `Dockerfile.server` / `Dockerfile.client` — Docker builds
- `docker-compose.yml` — Orchestration
