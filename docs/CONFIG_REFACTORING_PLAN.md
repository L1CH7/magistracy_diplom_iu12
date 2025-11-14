# Configuration Refactoring Plan

## Current State

### Problems

1. **Scattered Configs**: Python config classes in multiple locations
   - `src/client/config/` - 4 files (data, GUI, simulation, map)
   - `src/server/` - inline configs in app.py
   - `configs/` - 2 YAML files (car_profile, promtail)

2. **No Hot Reload**: Container rebuild required for config changes
   - Python configs embedded in containers
   - Volume mount only for `configs/car_profile.yaml`

3. **Python Format**: Using Python classes instead of YAML
   - Harder to edit (requires code knowledge)
   - No schema validation
   - Mixing code and data

4. **Tight Coupling**: Configs mixed with code logic
   - LOD_LAYERS in Python but not used by JS
   - MapRenderConfig not accessible to frontend

## Proposed Architecture

### Directory Structure

```
configs/
├── client/
│   ├── gui.yaml          # Window sizes, colors, styles
│   ├── data.yaml         # API endpoints, bboxes, timeouts
│   ├── simulation.yaml   # Agent params, FPS, speed limits
│   └── map.yaml          # LOD layers, colors, widths
├── server/
│   ├── api.yaml          # FastAPI config, CORS, middleware
│   ├── database.yaml     # PostGIS connection, pool size
│   └── routing.yaml      # pgRouting params, profiles
└── shared/
    ├── car_profile.yaml  # OSRM profile (existing)
    └── regions.yaml      # Convert regions.py to YAML
```

### Docker Volumes

In `docker-compose.yml`:

```yaml
services:
  client:
    volumes:
      - ./configs/client:/app/configs:ro  # Read-only mount
      
  server:
    volumes:
      - ./configs/server:/app/configs:ro
      - ./configs/shared:/app/configs/shared:ro
```

### Configuration Loading

**Base loader** (`src/utils/config_loader.py`):

```python
import yaml
from pathlib import Path
from typing import Any, Dict

class ConfigLoader:
    """Load and merge YAML configs with environment overrides."""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self._cache = {}
    
    def load(self, filename: str) -> Dict[str, Any]:
        """Load YAML file with caching."""
        if filename in self._cache:
            return self._cache[filename]
        
        path = self.config_dir / filename
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        self._cache[filename] = config
        return config
    
    def reload(self, filename: str) -> Dict[str, Any]:
        """Force reload (for hot reload)."""
        self._cache.pop(filename, None)
        return self.load(filename)
```

**Client usage**:

```python
# In src/client/main.py
from src.utils.config_loader import ConfigLoader

config = ConfigLoader(Path('configs/client'))
gui_config = config.load('gui.yaml')
data_config = config.load('data.yaml')
```

## Migration Steps

### Phase 1: Convert Client Configs (Priority: HIGH)

1. **Create YAML files**:
   - `configs/client/gui.yaml` from `GUIConfig`
   - `configs/client/data.yaml` from `DataConfig`
   - `configs/client/map.yaml` from `MapRenderConfig`
   - `configs/client/simulation.yaml` from `simulation_config`

2. **Add ConfigLoader utility**:
   - `src/utils/config_loader.py`
   - Support YAML loading with validation
   - Cache for performance

3. **Update client code**:
   - Replace `from src.client.config import DataConfig` with loader
   - Update all references to use dict access
   - Example: `DataConfig.API_TIMEOUT` → `config['api']['timeout']`

4. **Add volume mounts**:
   - Update `docker-compose.yml`
   - Mount `./configs/client` to `/app/configs`

5. **Test hot reload**:
   - Edit `configs/client/data.yaml` on host
   - Restart client container (no rebuild needed)
   - Verify changes applied

### Phase 2: Convert Server Configs (Priority: MEDIUM)

1. **Create YAML files**:
   - `configs/server/api.yaml` - FastAPI settings
   - `configs/server/database.yaml` - PostGIS connection
   - `configs/server/routing.yaml` - Route engine params

2. **Extract from app.py**:
   - CORS settings → `api.yaml`
   - Tile cache params → `routing.yaml`
   - Database connection → `database.yaml`

3. **Update server code**:
   - Load configs in `app.py` startup
   - Replace hardcoded values

4. **Add volume mounts** for server

### Phase 3: Dynamic LOD Config (Priority: HIGH)

**Problem**: JavaScript can't read Python LOD_LAYERS

**Solution**: Server endpoint + YAML config

1. **Create `configs/client/map.yaml`**:

```yaml
lod:
  layers:
    - name: highways
      minzoom: 0
      maxzoom: 10
      highways: [motorway, motorway_link, trunk, trunk_link, primary, primary_link]
      show_names: false
      show_refs: true
      base_width: 1.0
    
    - name: major_roads
      minzoom: 10
      maxzoom: 12
      highways: [motorway, motorway_link, trunk, trunk_link, primary, primary_link]
      show_names: false
      show_refs: true
      base_width: 1.5
    
    # ... 2 more layers

  colors:
    motorway: '#1e40af'
    trunk: '#6200ffff'
    primary: '#9c00aaff'
    # ... 14 types
  
  widths:
    motorway: 8
    trunk: 7
    primary: 6
    # ...
```

2. **Add server endpoint**:

```python
# In app.py
@app.get("/api/map/lod_config")
async def get_lod_config():
    """Return LOD configuration for MapLibre."""
    config = config_loader.load('client/map.yaml')
    return config['lod']
```

3. **Update JavaScript**:

```javascript
// In map-main.js
async function initMap() {
    const lod_config = await fetch('/api/map/lod_config').then(r => r.json());
    const style = buildStyleFromConfig(lod_config);
    map = new maplibregl.Map({ style });
}

function buildStyleFromConfig(config) {
    return {
        version: 8,
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        sources: { /* ... */ },
        layers: config.layers.map(buildLayerFromConfig)
    };
}
```

**Benefits**:
- Edit `configs/client/map.yaml` on host
- Refresh browser (Ctrl+R) to see changes
- No container rebuild
- No JavaScript editing

### Phase 4: Environment Overrides (Priority: LOW)

**Use case**: Different configs for dev/prod

```yaml
# configs/client/data.yaml
api:
  base_url: ${API_BASE_URL:http://localhost:8000}  # Default if env var not set
  timeout: ${API_TIMEOUT:600}

bboxes:
  moscow_small: [37.5609, 55.7510, 37.6016, 55.7631]
  moscow_center: [37.4, 55.5, 37.9, 55.9]
  default: ${DEFAULT_BBOX:moscow_small}  # Reference another key
```

**Loader with env vars**:

```python
import os
import re

def expand_env_vars(value: Any) -> Any:
    """Expand ${VAR:default} in strings."""
    if isinstance(value, str):
        pattern = r'\$\{(\w+):([^}]+)\}'
        def replace(match):
            var, default = match.groups()
            return os.getenv(var, default)
        return re.sub(pattern, replace, value)
    return value
```

## Benefits

### Developer Experience

✅ **Edit configs without rebuilding** (hot reload)  
✅ **YAML syntax highlighting** in editors  
✅ **Schema validation** (via yamllint + custom validator)  
✅ **Comments supported** in YAML  
✅ **Git-friendly** (easy diffs)  

### Operations

✅ **Environment-specific configs** (dev/staging/prod)  
✅ **Override via env vars** (Kubernetes-friendly)  
✅ **Volume mounts** (no baked-in configs)  
✅ **Reload without restart** (optional watch mode)  

### Architecture

✅ **Separation of concerns** (configs != code)  
✅ **Shared configs** between client/server (in `shared/`)  
✅ **Type safety** (optional Pydantic models from YAML)  
✅ **Dynamic reconfiguration** (API endpoint for LOD)  

## Implementation Timeline

| Phase | Task | Effort | Priority |
|-------|------|--------|----------|
| **1** | Convert client configs to YAML | 2h | HIGH |
| **1** | Add ConfigLoader utility | 1h | HIGH |
| **1** | Update client code | 2h | HIGH |
| **1** | Add volume mounts | 0.5h | HIGH |
| **3** | Dynamic LOD endpoint | 1h | HIGH |
| **3** | JavaScript config consumer | 2h | HIGH |
| **2** | Convert server configs | 2h | MEDIUM |
| **2** | Add server volume mounts | 0.5h | MEDIUM |
| **4** | Environment overrides | 1h | LOW |
| **Total** | | **12h** | |

## Testing Plan

### Phase 1 Test

1. Edit `configs/client/data.yaml`:
   ```yaml
   api:
     timeout: 300  # Change from 600
   ```

2. Restart client container:
   ```bash
   docker restart diplom-client-1
   ```

3. Verify timeout changed (no rebuild)

### Phase 3 Test

1. Edit `configs/client/map.yaml`:
   ```yaml
   lod:
     layers:
       - name: highways
         minzoom: 0
         maxzoom: 8  # Changed from 10
   ```

2. Refresh browser (Ctrl+R)

3. Verify highways disappear at zoom 9 (no container restart)

## Rollback Plan

If issues arise:

```bash
# Restore Python configs (keep both during migration)
git checkout HEAD -- src/client/config/*.py
docker compose restart client
```

Keep Python configs as fallback during Phase 1-2.

## Next Steps

Ready to implement? Start with:

1. Create `configs/client/` directory structure
2. Write `data.yaml` from `DataConfig` class
3. Test volume mount without code changes
4. Verify file accessible in container

Then proceed with ConfigLoader implementation.
