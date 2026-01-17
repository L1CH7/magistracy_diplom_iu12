# Configuration Audit & Migration Plan

## Current State Analysis

### ✅ Active Configs (KEEP & MIGRATE)

1. **src/utils/loguru_config.py**
   - Status: ACTIVE - used in app.py, main.py
   - Purpose: Loguru logger configuration (not data config, code behavior)
   - Action: KEEP as-is

2. **src/client/config/data_config.py**
   - Status: ACTIVE - used in api_workers.py
   - Classes: DataConfig, MapRenderConfig
   - Action: Migrate to `data.yaml` + `map.lod.yaml`

3. **src/client/config/gui_config.py**
   - Status: ACTIVE - used in UI
   - Action: Migrate to `gui.yaml`

4. **src/client/config/simulation_config.py**
   - Status: ACTIVE - used in simulation
   - Action: Migrate to `simulation.yaml`

5. **configs/car_profile.yaml**
   - Status: ACTIVE
   - Action: Move to `routing/car_profile.yaml`

6. **configs/regions.py**
   - Status: ACTIVE
   - Action: Convert to `regions.yaml`

### ❌ Dead Configs (DELETE)

1. **src/utils/logging_config.py** - NO imports (structlog deprecated)
2. **src/utils/logger.py** - NO imports (old structlog wrapper)

### 🔵 Keep External

**configs/promtail-config.yaml** - External Promtail service

## Final Structure

```
configs/
├── client/
│   ├── data.yaml          ✅ Created
│   ├── gui.yaml           ⏳ To create
│   ├── simulation.yaml    ⏳ To create
│   ├── map.lod.yaml       ⏳ Split from map.yaml
│   └── map.rendering.yaml ⏳ Split from map.yaml
├── routing/
│   └── car_profile.yaml   ⏳ Move from configs/
├── regions.yaml           ⏳ Convert from .py
└── promtail-config.yaml   ✅ Keep
```

## Why NO client/server/shared Directories?

Single `/configs` mounted to both containers:
- Client loads: `client/*.yaml`
- Server loads: `routing/*.yaml`, `regions.yaml`
- Both access same filesystem
- Simpler, clearer structure

## Migration Order

1. Create all YAML files
2. Test config_loader
3. Update docker-compose (simplified mount)
4. Migrate code module-by-module
5. Move old .py configs to .trash/ AFTER testing
6. Commit
