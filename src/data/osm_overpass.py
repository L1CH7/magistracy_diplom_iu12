import json
import os
from typing import Dict, Tuple, Optional
import requests
import time
import yaml
from pathlib import Path


def _load_overpass_config() -> dict:
    """Load Overpass config from configs/data-processor/overpass.yaml."""
    config_path = Path("/app/configs/data-processor/overpass.yaml")
    if not config_path.exists():
        # Try local dev path
        from src.utils.project_root import PROJECT_ROOT
        config_path = PROJECT_ROOT / "configs" / "data-processor" / "overpass.yaml"
    
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    # Fallback to hardcoded defaults
    return {
        "server_priority": "ru",
        "primary_servers": [
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.openstreetmap.ru/api/interpreter",
        ],
        "fallback_servers": [
            "https://overpass-api.de/api/interpreter",
        ],
        "timeout": 300,
    }


# Load config once at module import
_config = _load_overpass_config()

# Build server list based on priority
if _config.get("server_priority", "ru").lower() == "de":
    # German servers first (more reliable)
    OVERPASS_URLS = (
        _config.get("fallback_servers", [])
        + _config.get("primary_servers", [])
    )
else:
    # Russian servers first (default - faster for Moscow)
    OVERPASS_URLS = (
        _config.get("primary_servers", [])
        + _config.get("fallback_servers", [])
    )


def build_highway_query(bbox: Tuple[float, float, float, float]) -> str:
    """Build Overpass QL to fetch highway ways with MAXIMUM attributes.

    Fetches ALL road-related data:
    - All highway ways (motorway, trunk, primary, secondary, tertiary, residential, service, etc)
    - Traffic signals (highway=traffic_signals)
    - Pedestrian crossings (highway=crossing, crossing=*)
    - Railway level crossings (railway=level_crossing)
    - Traffic signs (traffic_sign=*)
    - Turn restrictions (type=restriction relations)
    
    ALL tags are automatically included:
    - Speed: maxspeed, maxspeed:forward/backward, maxspeed:lanes, maxspeed:conditional
    - Lanes: lanes, lanes:forward/backward, turn:lanes, change:lanes, width:lanes
    - Surface: surface, smoothness, width, lit, lane_markings
    - Structure: bridge, tunnel, layer, embankment, cutting
    - Cycling: cycleway, cycleway:left/right, sidewalk
    - Parking: parking:left/right, parking:lane:*:width
    - Access: access, motor_vehicle, hgv, bicycle, foot, maxheight, maxweight
    - Conditional: access:conditional, restriction:conditional
    
    bbox: (south, west, north, east)
    """
    s, w, n, e = bbox
    return f"""
    [out:json][timeout:180];
    (
      /* All highway ways - roads, paths, tracks */
      way["highway"]({s},{w},{n},{e});
      
      /* Traffic signals */
      node["highway"="traffic_signals"]({s},{w},{n},{e});
      
      /* Pedestrian crossings */
      node["highway"="crossing"]({s},{w},{n},{e});
      node["crossing"]({s},{w},{n},{e});
      
      /* Railway crossings */
      node["railway"="level_crossing"]({s},{w},{n},{e});
      
      /* Traffic signs */
      node["traffic_sign"]({s},{w},{n},{e});
      
      /* Turn restrictions (relations) */
      relation["type"="restriction"]({s},{w},{n},{e});
    );
    /* Get all nodes for ways and all members of relations */
    (._;>;);
    out body;
    """


async def fetch_overpass_from_url(
    url: str,
    query: str,
    timeout: int = 300
) -> Dict:
    """Fetch data from specific Overpass server (async version for retry logic).
    
    Args:
        url: Specific Overpass API URL to use
        query: Overpass QL query string
        timeout: Request timeout in seconds
    
    Returns:
        Parsed JSON response from Overpass API
    
    Raises:
        Exception: If request fails
    """
    import aiohttp
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data={"data": query},
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": "Diplom-NavMAS/0.1 (Research Project)"}
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return data


def fetch_overpass(
    query: str,
    url: Optional[str] = None,
    timeout: int = 300  # Increased from 180 to 300 (5 min)
) -> Dict:
    """Fetch data from Overpass API with automatic server fallback.
    
    Tries VK maps servers first, falls back to standard OSM on failure.
    
    Args:
        query: Overpass QL query string
        url: Optional explicit URL to use (skips auto-selection)
        timeout: Request timeout in seconds
    
    Returns:
        Parsed JSON response from Overpass API
    
    Raises:
        Exception: If all servers fail
    """
    urls_to_try = [url] if url else OVERPASS_URLS
    
    last_error = None
    for i, api_url in enumerate(urls_to_try):
        try:
            print(f"DEBUG: Trying Overpass server: {api_url}")
            r = requests.post(
                api_url,
                data={"data": query},
                timeout=timeout,
                headers={
                    "User-Agent": "Diplom-NavMAS/0.1 (Research Project)",
                }
            )
            r.raise_for_status()
            data = r.json()
            elem_count = len(data.get('elements', []))
            print(f"DEBUG: Success! Elements received: {elem_count}")
            return data
        except Exception as e:
            last_error = e
            print(f"WARN: Server {api_url} failed: {e}")
            if i < len(urls_to_try) - 1:
                print("DEBUG: Trying next server...")
                time.sleep(1)  # Brief delay before retry
            continue
    
    # All servers failed
    raise Exception(
        f"All Overpass servers failed. Last error: {last_error}"
    )


def fetch_road_graph_tiled(
    bbox: Tuple[float, float, float, float],
    tile_size_deg: float = 0.05,
    progress_callback=None
) -> Dict:
    """Fetch road graph data in tiles to avoid timeout.
    
    Args:
        bbox: (south, west, north, east) in degrees
        tile_size_deg: Size of tile in degrees (default: 0.05 ≈ 5.5km)
        progress_callback: Optional callback(current, total, tile_data)
    
    Returns:
        Combined Overpass JSON with all elements
    """
    s, w, n, e = bbox
    
    # Calculate tiles
    tiles = []
    lat = s
    while lat < n:
        lon = w
        while lon < e:
            tile_s = lat
            tile_w = lon
            tile_n = min(lat + tile_size_deg, n)
            tile_e = min(lon + tile_size_deg, e)
            tiles.append((tile_s, tile_w, tile_n, tile_e))
            lon += tile_size_deg
        lat += tile_size_deg
    
    total_tiles = len(tiles)
    print(f"DEBUG: Fetching {total_tiles} tiles (tile_size={tile_size_deg}°)")
    
    # Collect all elements
    all_elements = []
    seen_ids = set()
    
    for i, tile_bbox in enumerate(tiles):
        query = build_highway_query(tile_bbox)
        
        try:
            tile_data = fetch_overpass(query, timeout=60)
            elements = tile_data.get("elements", [])
            
            # Deduplicate elements by id
            new_elements = []
            for elem in elements:
                elem_id = (elem.get("type"), elem.get("id"))
                if elem_id not in seen_ids:
                    seen_ids.add(elem_id)
                    new_elements.append(elem)
            
            all_elements.extend(new_elements)
            
            print(
                f"DEBUG: Tile {i+1}/{total_tiles}: "
                f"{len(elements)} elements, "
                f"{len(new_elements)} new, "
                f"{len(all_elements)} total"
            )
            
            # Call progress callback if provided
            if progress_callback:
                progress_callback(i + 1, total_tiles, tile_data)
            
            # Brief delay to avoid rate limiting
            if i < total_tiles - 1:
                time.sleep(0.5)
                
        except Exception as e:
            print(f"ERROR: Failed to fetch tile {i+1}/{total_tiles}: {e}")
            # Continue with other tiles
            continue
    
    return {
        "version": 0.6,
        "generator": "fetch_road_graph_tiled",
        "elements": all_elements
    }


def save_json(data: Dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
