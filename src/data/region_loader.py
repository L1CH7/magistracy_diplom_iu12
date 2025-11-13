"""Universal region loader for OSM data into PostGIS cache."""

import asyncio
from typing import AsyncGenerator, Optional, Tuple
from configs.regions import (
    REGIONS,
    TILE_SIZE_DEG,
    OVERPASS_TIMEOUT_SEC,
    TILE_FETCH_DELAY_SEC
)
from src.data.postgis_manager import PostGISManager
from loguru import logger as log



async def load_region_to_cache(
    region_name: str
) -> AsyncGenerator[str, None]:
    """Load region OSM data into PostGIS cache.
    
    Args:
        region_name: Name from REGIONS config
        
    Yields:
        NDJSON progress messages
        
    Raises:
        ValueError: If region not found in config
    """
    import json
    
    # Check region exists
    if region_name not in REGIONS:
        yield json.dumps({
            'type': 'error',
            'message': f'Region "{region_name}" not found in config',
            'available_regions': list(REGIONS.keys()),
        }) + '\n'
        return
    
    bbox = REGIONS[region_name]
    db = PostGISManager()
    
    # Check if already cached
    if db.is_region_cached(region_name):
        log.info(f"Region ALREADY cached: {region_name}")
        yield json.dumps({
            'type': 'info',
            'message': f'Region "{region_name}" already cached',
            'region': region_name,
        }) + '\n'
        
        # Return cached data
        geojson = db.get_roads_geojson(tuple(bbox))
        
        yield json.dumps({
            'type': 'complete',
            'cached': True,
            'geojson': geojson,
            'region': region_name,
        }) + '\n'
        return
    
    # Create region metadata
    region_id = db.create_region(region_name, tuple(bbox))
    
    log.info(
        f"Region load START: region={region_name} id={region_id} "
        f"bbox={bbox}"
    )
    
    # Calculate tiles
    tiles = _calculate_tiles(bbox, TILE_SIZE_DEG)
    total_tiles = len(tiles)
    
    log.info(f"Tiles calculated: total={total_tiles} region={region_name}")
    
    yield json.dumps({
        'type': 'start',
        'total_tiles': total_tiles,
        'region': region_name,
        'bbox': bbox,
    }) + '\n'
    
    # Fetch and store tiles
    all_ways_count = 0
    all_elements_count = 0
    
    # Import here to avoid circular dependency
    from src.data.osm_overpass import fetch_overpass, build_highway_query
    
    for i, tile_bbox in enumerate(tiles):
        query = build_highway_query(tile_bbox)
        
        # Fetch tile data
        loop = asyncio.get_event_loop()
        try:
            tile_data = await loop.run_in_executor(
                None,
                lambda q=query: fetch_overpass(q, timeout=OVERPASS_TIMEOUT_SEC)
            )
        except Exception as e:
            log.error(
                f"Tile fetch FAILED: tile={i+1}/{total_tiles} "
                f"error={str(e)}"
            )
            yield json.dumps({
                'type': 'error',
                'tile': i + 1,
                'message': f'Tile {i+1} failed: {str(e)}',
            }) + '\n'
            continue
        
        elements = tile_data.get("elements", [])
        
        # Build nodes dict
        nodes = {
            el["id"]: el
            for el in elements
            if el.get("type") == "node"
        }
        
        ways = [
            el for el in elements
            if el.get("type") == "way"
        ]
        
        # Prepare ways for bulk insert
        ways_data = []
        for way in ways:
            tags = way.get("tags", {})
            if not tags.get("highway"):
                continue
            
            node_ids = way.get("nodes", [])
            coords = []
            for nid in node_ids:
                n = nodes.get(nid)
                if n and "lon" in n and "lat" in n:
                    coords.append([n["lon"], n["lat"]])
            
            if len(coords) >= 2:
                ways_data.append((way["id"], coords, tags))
        
        # Bulk insert
        if ways_data:
            db.bulk_insert_ways(ways_data, region=region_name)
            all_ways_count += len(ways_data)
        
        all_elements_count += len(elements)
        
        # Send progress
        yield json.dumps({
            'type': 'progress',
            'current_tile': i + 1,
            'total_tiles': total_tiles,
            'ways_so_far': all_ways_count,
            'elements_so_far': all_elements_count,
            'percent': round((i + 1) / total_tiles * 100, 1),
        }) + '\n'
        
        log.debug(
            f"Tile processed: region={region_name} "
            f"tile={i+1}/{total_tiles} ways={len(ways_data)} "
            f"total_ways={all_ways_count}"
        )
        
        # Delay to avoid rate limiting
        await asyncio.sleep(TILE_FETCH_DELAY_SEC)
    
    # Mark region as complete
    db.mark_region_complete(region_name, all_ways_count, all_elements_count)
    
    log.info(
        f"Region load COMPLETE: region={region_name} "
        f"total_ways={all_ways_count} total_elements={all_elements_count}"
    )
    
    # Return final GeoJSON
    geojson = db.get_roads_geojson(tuple(bbox))
    
    yield json.dumps({
        'type': 'complete',
        'cached': False,
        'geojson': geojson,
        'total_ways': all_ways_count,
        'total_elements': all_elements_count,
        'region': region_name,
    }) + '\n'


def _calculate_tiles(
    bbox: list,
    tile_size: float
) -> list[Tuple[float, float, float, float]]:
    """Calculate tiles for splitting large bbox.
    
    Args:
        bbox: [min_lon, min_lat, max_lon, max_lat]
        tile_size: Size in degrees
        
    Returns:
        List of (south, west, north, east) tuples
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    tiles = []
    
    lat = min_lat
    while lat < max_lat:
        lon = min_lon
        while lon < max_lon:
            tile_s = lat
            tile_w = lon
            tile_n = min(lat + tile_size, max_lat)
            tile_e = min(lon + tile_size, max_lon)
            tiles.append((tile_s, tile_w, tile_n, tile_e))
            lon += tile_size
        lat += tile_size
    
    return tiles
