#!/usr/bin/env python3
"""
Test script for road graph API endpoint.
Tests the full cycle: fetch from OSM, convert to GeoJSON, display progress.
"""
import requests
import json
import time

SERVER_URL = "http://localhost:8000"

def test_fetch_road_graph():
    """Test /osm/fetch_road_graph endpoint with streaming."""
    # Test bbox: Moscow district (sw=[37.5609, 55.7510], ne=[37.6016, 55.7631])
    bbox = [37.5609, 55.7510, 37.6016, 55.7631]
    
    print(f"Fetching road graph for bbox: {bbox}")
    print("=" * 60)
    
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
            print(f"ERROR: Server returned {resp.status_code}")
            print(resp.text)
            return False
        
        geojson = None
        line_count = 0
        
        for line in resp.iter_lines():
            if not line:
                continue
            
            line_count += 1
            data = json.loads(line.decode('utf-8'))
            msg_type = data.get("type")
            
            if msg_type == "progress":
                current = data.get("current", 0)
                total = data.get("total", 0)
                elements_count = data.get("elements_count", 0)
                
                print(
                    f"[Progress] Tile {current}/{total}, "
                    f"elements: {elements_count}"
                )
            
            elif msg_type == "complete":
                geojson = data.get("geojson")
                total_ways = data.get("total_ways", 0)
                total_elements = data.get("total_elements", 0)
                
                elapsed = time.time() - start_time
                print("=" * 60)
                print(f"✓ Complete!")
                print(f"  Total ways: {total_ways}")
                print(f"  Total elements: {total_elements}")
                print(f"  Time elapsed: {elapsed:.1f}s")
                print(f"  Messages received: {line_count}")
                
                # Analyze GeoJSON
                if geojson:
                    features = geojson.get("features", [])
                    print(f"  GeoJSON features: {len(features)}")
                    
                    # Sample first feature
                    if features:
                        first = features[0]
                        props = first.get("properties", {})
                        print(f"\n  Sample feature:")
                        print(f"    highway: {props.get('highway')}")
                        print(f"    lanes: {props.get('lanes')}")
                        print(f"    maxspeed: {props.get('maxspeed')}")
                        print(f"    oneway: {props.get('oneway')}")
                        
                        coords = first.get("geometry", {}).get("coordinates", [])
                        print(f"    coordinates: {len(coords)} points")
                
                return True
            
            elif msg_type == "error":
                error_msg = data.get("message", "Unknown error")
                print(f"✗ ERROR: {error_msg}")
                return False
        
        print("✗ No complete message received")
        return False
        
    except Exception as e:
        print(f"✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Road Graph API Test")
    print("=" * 60)
    print()
    
    success = test_fetch_road_graph()
    
    print()
    print("=" * 60)
    if success:
        print("✓ TEST PASSED")
    else:
        print("✗ TEST FAILED")
    print("=" * 60)
