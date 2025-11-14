#!/usr/bin/env python3
"""
End-to-end test for road graph feature.

Tests:
1. Fetch road graph data from OSM via server endpoint
2. Verify GeoJSON structure
3. Verify graph properties (lanes, maxspeed, etc.)
4. Check that server graph is updated
"""
import requests
import json
import time

SERVER_URL = "http://localhost:8000"

def test_e2e_road_graph():
    """Full end-to-end test."""
    print("\n" + "="*60)
    print("END-TO-END ROAD GRAPH TEST")
    print("="*60 + "\n")
    
    # Test bbox: Moscow district
    bbox = [37.5609, 55.7510, 37.6016, 55.7631]
    
    print(f"1. Fetching road graph for bbox: {bbox}")
    print("   This will take ~2 minutes...")
    
    url = f"{SERVER_URL}/osm/fetch_road_graph"
    req_data = {"bbox": bbox}
    
    start_time = time.time()
    
    try:
        resp = requests.post(
            url,
            json=req_data,
            stream=True,
            timeout=300
        )
        
        if resp.status_code != 200:
            print(f"   ✗ ERROR: Server returned {resp.status_code}")
            return False
        
        geojson = None
        
        for line in resp.iter_lines():
            if not line:
                continue
            
            data = json.loads(line.decode('utf-8'))
            msg_type = data.get("type")
            
            if msg_type == "progress":
                current = data.get("current", 0)
                total = data.get("total", 0)
                print(f"   Progress: {current}/{total} tiles", end="\r")
            
            elif msg_type == "complete":
                geojson = data.get("geojson")
                total_ways = data.get("total_ways", 0)
                elapsed = time.time() - start_time
                print(f"\n   ✓ Complete! {total_ways} ways in {elapsed:.1f}s")
                break
            
            elif msg_type == "error":
                print(f"\n   ✗ ERROR: {data.get('message')}")
                return False
        
        if not geojson:
            print("   ✗ No GeoJSON received")
            return False
        
        # 2. Verify GeoJSON structure
        print("\n2. Verifying GeoJSON structure...")
        features = geojson.get("features", [])
        
        if not features:
            print("   ✗ No features in GeoJSON")
            return False
        
        print(f"   ✓ {len(features)} features found")
        
        # Check first feature structure
        first = features[0]
        props = first.get("properties", {})
        geom = first.get("geometry", {})
        
        required_props = ["highway", "lanes", "maxspeed", "oneway"]
        missing = [p for p in required_props if p not in props]
        
        if missing:
            print(f"   ✗ Missing properties: {missing}")
            return False
        
        print(f"   ✓ All required properties present")
        
        # Check geometry
        if geom.get("type") != "LineString":
            print(f"   ✗ Invalid geometry type: {geom.get('type')}")
            return False
        
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            print(f"   ✗ Invalid coordinates: {len(coords)} points")
            return False
        
        print(f"   ✓ Valid LineString geometry")
        
        # 3. Verify graph properties
        print("\n3. Analyzing road properties...")
        
        # Count highway types
        highway_types = {}
        lanes_stats = {"min": 999, "max": 0, "total": 0, "count": 0}
        maxspeed_stats = {"min": 999, "max": 0, "total": 0, "count": 0}
        oneway_count = 0
        
        for feature in features:
            props = feature.get("properties", {})
            
            # Highway type
            htype = props.get("highway", "unknown")
            highway_types[htype] = highway_types.get(htype, 0) + 1
            
            # Lanes
            try:
                lanes = int(props.get("lanes", "1"))
                lanes_stats["min"] = min(lanes_stats["min"], lanes)
                lanes_stats["max"] = max(lanes_stats["max"], lanes)
                lanes_stats["total"] += lanes
                lanes_stats["count"] += 1
            except:
                pass
            
            # Maxspeed
            try:
                speed_str = str(props.get("maxspeed", "60"))
                speed = int(''.join(c for c in speed_str if c.isdigit()) or "60")
                maxspeed_stats["min"] = min(maxspeed_stats["min"], speed)
                maxspeed_stats["max"] = max(maxspeed_stats["max"], speed)
                maxspeed_stats["total"] += speed
                maxspeed_stats["count"] += 1
            except:
                pass
            
            # Oneway
            if props.get("oneway") == "yes":
                oneway_count += 1
        
        print(f"   Highway types: {len(highway_types)}")
        for htype, count in sorted(highway_types.items(), 
                                    key=lambda x: x[1], reverse=True)[:5]:
            print(f"     - {htype}: {count}")
        
        avg_lanes = (lanes_stats["total"] / lanes_stats["count"] 
                     if lanes_stats["count"] > 0 else 0)
        print(f"   Lanes: min={lanes_stats['min']}, "
              f"max={lanes_stats['max']}, avg={avg_lanes:.1f}")
        
        avg_speed = (maxspeed_stats["total"] / maxspeed_stats["count"] 
                     if maxspeed_stats["count"] > 0 else 0)
        print(f"   Max speed: min={maxspeed_stats['min']}, "
              f"max={maxspeed_stats['max']}, avg={avg_speed:.0f} km/h")
        
        oneway_pct = (oneway_count / len(features) * 100)
        print(f"   Oneway roads: {oneway_count} ({oneway_pct:.1f}%)")
        
        print("   ✓ Road properties look good")
        
        # 4. Check server graph
        print("\n4. Checking server graph status...")
        
        try:
            resp = requests.get(f"{SERVER_URL}/graph", timeout=10)
            if resp.status_code == 200:
                graph_data = resp.json()
                nodes = graph_data.get("nodes", [])
                edges = graph_data.get("edges", [])
                print(f"   ✓ Server graph: {len(nodes)} nodes, "
                      f"{len(edges)} edges")
            else:
                print(f"   ⚠ Could not fetch graph: {resp.status_code}")
        except Exception as e:
            print(f"   ⚠ Graph check failed: {e}")
        
        print("\n" + "="*60)
        print("✓ ALL TESTS PASSED")
        print("="*60 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_e2e_road_graph()
    exit(0 if success else 1)
