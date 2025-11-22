#!/usr/bin/env python3
"""
Test YAML configuration loading with !include support.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config_loader import config_loader

def test_configs():
    """Test loading all configs."""
    
    print("=" * 80)
    print("Testing Configuration Loading")
    print("=" * 80)
    
    # Test 1: data.yaml
    print("\n[1] Loading client/data.yaml...")
    data = config_loader.load('client/data.yaml')
    print(f"✅ Keys: {list(data.keys())}")
    print(f"   API timeout: {data['api']['timeout_default']}s")
    print(f"   Bboxes: {list(data['bboxes'].keys())}")
    
    # Test 2: gui.yaml
    print("\n[2] Loading client/gui.yaml...")
    gui = config_loader.load('client/gui.yaml')
    print(f"✅ Keys: {list(gui.keys())}")
    print(f"   Window: {gui['window']['width']}x{gui['window']['height']}")
    print(f"   Marker colors: from={gui['markers']['from_color']}, to={gui['markers']['to_color']}")
    
    # Test 3: simulation.yaml
    print("\n[3] Loading client/simulation.yaml...")
    sim = config_loader.load('client/simulation.yaml')
    print(f"✅ Keys: {list(sim.keys())}")
    print(f"   Speed: {sim['speed']['default']}x (range: {sim['speed']['min']}-{sim['speed']['max']})")
    print(f"   FPS: {sim['fps']['default']} (range: {sim['fps']['min']}-{sim['fps']['max']})")
    
    # Test 4: map.yaml with includes
    print("\n[4] Loading client/map.yaml (with !include)...")
    map_cfg = config_loader.load('client/map.yaml')
    print(f"✅ Top keys: {list(map_cfg.keys())}")
    print(f"   LOD layers: {len(map_cfg['lod']['layers'])}")
    for layer in map_cfg['lod']['layers']:
        print(f"      - {layer['name']}: z{layer['minzoom']}-{layer['maxzoom']} ({len(layer['highways'])} highways)")
    print(f"   Colors: {len(map_cfg['rendering']['colors'])} highway types")
    print(f"   Widths: {len(map_cfg['rendering']['widths'])} types")
    print(f"   Highway groups: {list(map_cfg['rendering']['highway_groups'].keys())}")
    
    # Test 5: routing/car_profile.yaml
    print("\n[5] Loading routing/car_profile.yaml...")
    routing = config_loader.load('routing/car_profile.yaml')
    print(f"✅ Keys: {list(routing.keys())}")
    print(f"   Profile: {routing['profile']}")
    print(f"   Vehicle: {routing['vehicle']}")
    
    # Test 6: common.yaml
    print("\n[6] Loading common.yaml...")
    common = config_loader.load('common.yaml')
    print(f"✅ Keys: {list(common.keys())}")
    print(f"   API base URL: {common['api']['base_url']}")
    print(f"   Timeout default: {common['timeouts']['default']}s")
    print(f"   Log level: {common['logging']['level']}")
    
    # Test 8: server configs
    print("\n[8] Loading server/api.yaml...")
    srv_api = config_loader.load('server/api.yaml')
    print(f"✅ Keys: {list(srv_api.keys())}")
    print(f"   Server: {srv_api['server']['host']}:{srv_api['server']['port']}")
    print(f"   CORS origins: {srv_api['cors']['allow_origins']}")
    
    print("\n[9] Loading server/database.yaml...")
    srv_db = config_loader.load('server/database.yaml')
    print(f"✅ Keys: {list(srv_db.keys())}")
    print(f"   Postgres host: {srv_db['postgres']['host']}")
    print(f"   Schemas: {list(srv_db['schemas'].values())}")
    
    print("\n[10] Loading server/routing.yaml...")
    srv_routing = config_loader.load('server/routing.yaml')
    print(f"✅ Keys: {list(srv_routing.keys())}")
    print(f"   K routes: {srv_routing['routing']['k_routes']}")
    print(f"   Overpass endpoints: {len(srv_routing['overpass']['endpoints'])}")
    
    print("\n" + "=" * 80)
    print("✅ All configs loaded successfully!")
    print("=" * 80)
    
    # Cache stats
    cached = config_loader.get_cached_files()
    print(f"\n📦 Cached files: {len(cached)}")
    for f in cached:
        print(f"   - {f}")


if __name__ == '__main__':
    try:
        test_configs()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
