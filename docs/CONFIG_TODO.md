# Configuration Migration TODO

## ✅ Completed
- Created YAML config system with !include support
- Added ConfigLoader with caching and hot reload
- Created all YAML configs:
  - client/*:  data, gui, simulation, map (with LOD + rendering)
  - server/*: api, database, routing
  - routing/car_profile.yaml
  - regions.yaml
  - common.yaml
- Fixed JS QWebChannel error (create once, reuse)
- Fixed car_profile.yaml path in osrm_profile.py
- Fixed api_workers.py to use config_loader
- Moved old configs to .trash/2025-11-14-config-migration/

## 🔴 TODO: Remove Python Config Classes

### Priority: HIGH
Need to remove src/client/config/ entirely and migrate all imports.

### Files to Update:

1. **src/client/ui/widgets/simulation_panel.py**
   ```python
   # Before:
   from src.client.config.simulation_config import simulation_config
   self.speed_spinbox.setRange(
       simulation_config.min_sim_speed,
       simulation_config.max_sim_speed
   )
   
   # After:
   from src.utils.config_loader import config_loader
   config = config_loader.load('client/simulation.yaml')
   self.speed_spinbox.setRange(
       config['speed']['min'],
       config['speed']['max']
   )
   ```

2. **src/client/ui/main_window_handlers.py**
   - Line 970, 1130: `simulation_config` imports
   - Line 1043: `simulation_config.teleport_threshold_multiplier`
   - Line 1131: `simulation_config.debug_teleportations`

3. **Search for all GUIConfig usage** (if any)

### After Migration:
```bash
# Remove entire config directory
rm -rf src/client/config/

# Test everything still works
docker compose restart client
# Test UI, routes, simulation

# Commit
git add -A
git commit -m "refactor: remove Python config classes, use YAML only"
```

## 🐛 Known Issues

### 1. Route Building Sometimes Fails
**Symptom**: Routes build "через раз" (intermittently)
**Status**: TODO - investigate snap_point_to_graph
**Location**: src/routing/pathfinding.py or route_builder.py

### 2. Teleport Detection Uses Old Config
**Status**: Will be fixed when simulation_config removed
**Files**: main_window_handlers.py lines 1043, 1131

## 📝 Future Improvements

1. **Config Validation**
   - Add JSON Schema validation for YAML files
   - Validate on startup, fail fast with clear errors

2. **Config Hot Reload in UI**
   - Watch YAML files for changes
   - Reload without restart (for dev)

3. **Environment-Specific Configs**
   - configs/dev/*.yaml
   - configs/prod/*.yaml
   - Override mechanism

4. **Type Safety**
   - Generate TypedDict classes from YAML
   - IDE autocomplete for config keys
