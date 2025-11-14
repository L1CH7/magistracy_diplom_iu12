#!/usr/bin/env python3
"""Test progress bar for OSM tile downloads.

This script tests the progress bar functionality by requesting
an uncached bbox and monitoring progress updates.
"""

import urllib.request
import urllib.parse
import json
import sys

# Use bbox in a different region (guaranteed not cached)
# Tula region: 4-5 tiles for reasonable test duration
UNCACHED_BBOX = [37.55, 54.15, 37.65, 54.25]  # ~4 tiles

def test_progress():
    """Test progress bar with streaming response."""
    url = "http://localhost:8000/osm/fetch_road_graph"
    data = json.dumps({"bbox": UNCACHED_BBOX}).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
    }
    
    req = urllib.request.Request(url, data=data, headers=headers)
    
    print(f"Testing bbox: {UNCACHED_BBOX}")
    print("Expected: ~4 tiles to download")
    print("-" * 60)
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            progress_count = 0
            for line in response:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                    
                try:
                    msg = json.loads(line)
                    msg_type = msg.get('type')
                    
                    if msg_type == 'info':
                        print(f"ℹ️  INFO: {msg.get('message')}")
                    
                    elif msg_type == 'progress':
                        progress_count += 1
                        percent = msg.get('percent', 0)
                        message = msg.get('message', 'N/A')
                        current = msg.get('current', 0)
                        total = msg.get('total', 0)
                        tile = msg.get('tile', 'N/A')
                        
                        print(f"⏳ PROGRESS #{progress_count}: {message} | "
                              f"Percent: {percent}% | Tile: {tile}")
                    
                    elif msg_type == 'complete':
                        total_ways = msg.get('total_ways', 0)
                        is_cached = msg.get('is_cached', False)
                        features = len(msg.get('geojson', {}).get('features', []))
                        
                        print("-" * 60)
                        print(f"✅ COMPLETE!")
                        print(f"   Total ways: {total_ways}")
                        print(f"   GeoJSON features: {features}")
                        print(f"   From cache: {is_cached}")
                        print(f"   Progress updates received: {progress_count}")
                        break
                    
                    elif msg_type == 'error':
                        print(f"❌ ERROR: {msg.get('error')}")
                        return False
                        
                except json.JSONDecodeError as e:
                    print(f"⚠️  JSON decode error: {e}")
                    continue
            
            if progress_count == 0:
                print("\n⚠️  WARNING: No progress updates received!")
                print("This might mean the bbox was already cached.")
                return False
            
            return True
            
    except urllib.error.URLError as e:
        print(f"❌ Connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("PROGRESS BAR TEST")
    print("=" * 60)
    print()
    
    success = test_progress()
    
    print()
    print("=" * 60)
    if success:
        print("✅ Test PASSED: Progress bar works correctly!")
    else:
        print("❌ Test FAILED: Check issues above")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
