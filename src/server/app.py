from __future__ import annotations

import os
from typing import List, Dict, Any
from itertools import cycle

import networkx as nx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.data.graph_builder import build_graph_from_overpass, nearest_node
from src.data.osm_loader import fetch_osm, save_json
from src.routing.simple_engine import SimpleRouteEngine, Route


app = FastAPI(title="Coordinator Server")


class Point(BaseModel):
    lat: float
    lon: float


class RouteRequest(BaseModel):
    start: Point
    end: Point
    k: int = Field(1, ge=1, le=5)


class RouteResponse(BaseModel):
    routes: List[Dict[str, Any]]


class AgentParamsModel(BaseModel):
    max_speed: float = Field(ge=0.1)
    power: float = Field(ge=0.0)
    length: float = Field(ge=0.1)
    width: float = Field(ge=0.1)


class AgentStartRequest(BaseModel):
    route_nodes: List[int]
    params: AgentParamsModel


class AgentState(BaseModel):
    agent_id: int
    index: int
    done: bool
    position: Dict[str, float]
    progress: float = 0.0


class OsmLoadRequest(BaseModel):
    bbox: List[float] = Field(
        ..., min_items=4, max_items=4
    )  # [min_lon, min_lat, max_lon, max_lat]


G: nx.DiGraph | None = None
engine: SimpleRouteEngine | None = None
agents: Dict[int, Dict] = {}
route_cache: Dict[str, RouteResponse] = {}
next_agent_id = 1
_tile_hosts = cycle(["a", "b", "c"])  # for upstream OSM subdomains


def _load_graph() -> nx.DiGraph:
    """Load graph from OSM data if available, otherwise use demo."""
    json_path = os.getenv("OSM_JSON_PATH", "data/osm_data.json")
    
    # Try to load OSM data
    if os.path.exists(json_path):
        try:
            print(f"DEBUG: Loading graph from {json_path}")
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            graph = build_graph_from_overpass(data)
            print(
                f"DEBUG: Loaded OSM graph with {graph.number_of_nodes()} "
                f"nodes and {graph.number_of_edges()} edges"
            )
            return graph
        except Exception as e:
            print(f"WARN: Failed to load OSM graph: {e}")
            print("DEBUG: Falling back to demo graph")
    
    # Demo graph fallback
    print("DEBUG: Using demo graph (no OSM data available)")
    demo = nx.DiGraph()
    demo.add_node(1, lat=55.75, lon=37.61)
    demo.add_node(2, lat=55.76, lon=37.62)
    demo.add_node(3, lat=55.77, lon=37.63)
    edges = [
        (1, 2, 10.0, 1000.0),
        (2, 3, 12.0, 1100.0),
        (1, 3, 30.0, 2500.0),
    ]
    for u, v, t, l in edges:
        demo.add_edge(u, v, time_s=t, length_m=l)
        demo.add_edge(v, u, time_s=t, length_m=l)
    return demo


@app.on_event("startup")
def startup_event() -> None:
    global G, engine
    try:
        G = _load_graph()
        print(f"DEBUG: Graph loaded with {G.number_of_nodes()} nodes")
        engine = SimpleRouteEngine(G)
        print("DEBUG: Engine initialized successfully")
    except Exception as e:
        print(f"ERROR during startup: {e}")
        import traceback
        traceback.print_exc()
        raise


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "graph_loaded": G is not None,
        "nodes": G.number_of_nodes() if G else 0,
        "edges": G.number_of_edges() if G else 0,
        "engine": engine is not None
    }


@app.post("/route", response_model=RouteResponse)
def post_route(req: RouteRequest) -> RouteResponse:
    cache_key = (
        f"{req.start.lat:.6f},{req.start.lon:.6f}_"
        f"{req.end.lat:.6f},{req.end.lon:.6f}_{req.k}"
    )
    if cache_key in route_cache:
        return route_cache[cache_key]
    if engine is None or G is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    s = nearest_node(G, req.start.lat, req.start.lon)
    t = nearest_node(G, req.end.lat, req.end.lon)
    routes = []
    for i in range(req.k):
        # For simplicity, return the same route k times
        route: Route = engine.get_route(s, t)
        routes.append({
            "nodes": route.nodes,
            "total_distance": route.total_distance,
            "estimated_time": route.estimated_time,
            "positions": [
                {"lat": G.nodes[n]["lat"], "lon": G.nodes[n]["lon"]}
                for n in route.nodes
            ]
        })
    response = RouteResponse(routes=routes)
    route_cache[cache_key] = response
    return response


@app.post("/agent/start", response_model=AgentState)
def agent_start(req: AgentStartRequest) -> AgentState:
    global next_agent_id
    if G is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    if not req.route_nodes:
        raise HTTPException(status_code=400, detail="Empty route")
    aid = next_agent_id
    next_agent_id += 1
    agents[aid] = {
        "nodes": req.route_nodes,
        "index": 0,
        "params": req.params.dict(),
        "progress": 0.0
    }
    n0 = req.route_nodes[0]
    pos = {
        "lat": float(G.nodes[n0]["lat"]),
        "lon": float(G.nodes[n0]["lon"]),
    }
    return AgentState(agent_id=aid, index=0, done=False, position=pos)


@app.post("/agent/{agent_id}/step", response_model=AgentState)
def agent_step(agent_id: int) -> AgentState:
    if G is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    st = agents.get(agent_id)
    if not st:
        raise HTTPException(status_code=404, detail="Agent not found")
    idx = st["index"]
    nodes = st["nodes"]
    progress = st["progress"]
    if idx >= len(nodes) - 1:
        done = True
        nid = nodes[idx]
        pos = {
            "lat": float(G.nodes[nid]["lat"]),
            "lon": float(G.nodes[nid]["lon"]),
        }
    else:
        current_n = nodes[idx]
        next_n = nodes[idx + 1]
        current_pos = G.nodes[current_n]
        next_pos = G.nodes[next_n]
        dist = (
            (
                (next_pos["lat"] - current_pos["lat"]) ** 2
                + (next_pos["lon"] - current_pos["lon"]) ** 2
            )
            ** 0.5
            * 111320
        )
        speed_mps = st["params"]["max_speed"] / 3.6
        time_to_next = dist / speed_mps if speed_mps > 0 else 1
        progress += 0.1  # step every 0.1 sec
        if progress >= time_to_next:
            st["index"] = idx + 1
            st["progress"] = 0.0
            pos = {
                "lat": float(next_pos["lat"]),
                "lon": float(next_pos["lon"]),
            }
        else:
            st["progress"] = progress
            lat = current_pos["lat"] + (
                (next_pos["lat"] - current_pos["lat"]) *
                (progress / time_to_next)
            )
            lon = current_pos["lon"] + (
                (next_pos["lon"] - current_pos["lon"]) *
                (progress / time_to_next)
            )
            pos = {"lat": lat, "lon": lon}
        done = False
    return AgentState(
        agent_id=agent_id,
        index=idx,
        done=done,
        position=pos,
        progress=progress,
    )


@app.get("/graph")
def get_graph():
    global G
    if G is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    nodes = []
    edges = []
    for n, d in G.nodes(data=True):
        nodes.append({'id': n, 'lat': d['lat'], 'lon': d['lon']})
    for u, v in G.edges():
        edges.append({'u': u, 'v': v})
    return {'nodes': nodes, 'edges': edges}


@app.post("/nearest", response_model=Point)
def get_nearest(req: Point) -> Point:
    global G
    if G is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    n = nearest_node(G, req.lat, req.lon)
    return Point(lat=G.nodes[n]["lat"], lon=G.nodes[n]["lon"])


@app.post("/osm/load")
def osm_load(req: OsmLoadRequest) -> dict:
    try:
        # UI provides bbox as [min_lon, min_lat, max_lon, max_lat].
        # Overpass helper expects (south, west, north, east)
        # => (min_lat, min_lon, max_lat, max_lon)
        min_lon, min_lat, max_lon, max_lat = req.bbox
        overpass_bbox = (min_lat, min_lon, max_lat, max_lon)
        data = fetch_osm(overpass_bbox)
        json_path = os.getenv("OSM_JSON_PATH", "data/osm_data.json")
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        save_json(data, json_path)
        # Reload graph
        global G, engine
        G = build_graph_from_overpass(data)
        engine = SimpleRouteEngine(G)
        return {
            "status": "success",
            "message": f"OSM data loaded and graph rebuilt from {json_path}"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load OSM: {str(e)}"
        )


class RoadGraphRequest(BaseModel):
    bbox: List[float] = Field(
        ..., min_items=4, max_items=4
    )  # [min_lon, min_lat, max_lon, max_lat]


@app.post("/osm/fetch_road_graph")
async def fetch_road_graph(req: RoadGraphRequest):
    """Fetch road graph data with PostGIS caching.
    
    Flow:
    1. Check if bbox overlaps with cached regions
    2. If fully cached, return from PostGIS immediately
    3. If not cached, fetch from Overpass + cache + return
    
    Returns NDJSON stream with progress and final GeoJSON.
    """
    from src.data.postgis_manager import PostGISManager
    from src.data.osm_overpass import fetch_overpass, build_highway_query
    import asyncio
    from fastapi.responses import StreamingResponse
    import json as json_module
    
    min_lon, min_lat, max_lon, max_lat = req.bbox
    bbox_tuple = (min_lon, min_lat, max_lon, max_lat)
    
    db = PostGISManager()
    
    async def generate():
        # Try to get from PostGIS cache first
        try:
            geojson = db.get_roads_geojson(bbox_tuple)
            if geojson and geojson.get('features'):
                # Cache hit!
                print(f"DEBUG: Bbox cache HIT for {bbox_tuple}")
                yield json_module.dumps({
                    'type': 'info',
                    'message': 'Data loaded from PostGIS cache',
                }) + '\n'
                
                yield json_module.dumps({
                    'type': 'complete',
                    'cached': True,
                    'geojson': geojson,
                    'total_ways': len(geojson.get('features', [])),
                }) + '\n'
                return
        except Exception as e:
            print(f"WARN: PostGIS cache check failed: {e}")
        
        # Cache miss - fetch from Overpass
        print(f"DEBUG: Bbox cache MISS for {bbox_tuple}, fetching from Overpass")
        
        bbox = (min_lat, min_lon, max_lat, max_lon)
        
        # Calculate tiles
        tile_size_deg = 0.05
        s, w, n, e = bbox
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
        print(f"DEBUG: Will fetch {total_tiles} tiles")
        
        # Collect all elements
        all_elements = []
        seen_ids = set()
        
        try:
            for i, tile_bbox in enumerate(tiles):
                query = build_highway_query(tile_bbox)
                
                # Fetch tile (blocking, run in executor)
                loop = asyncio.get_event_loop()
                tile_data = await loop.run_in_executor(
                    None,
                    lambda q=query: fetch_overpass(q, timeout=60)
                )
                
                elements = tile_data.get("elements", [])
                
                # Deduplicate elements
                new_count = 0
                for elem in elements:
                    elem_id = (elem.get("type"), elem.get("id"))
                    if elem_id not in seen_ids:
                        seen_ids.add(elem_id)
                        all_elements.append(elem)
                        new_count += 1
                
                print(
                    f"DEBUG: Tile {i+1}/{total_tiles}: "
                    f"{len(elements)} raw, {new_count} new, "
                    f"{len(all_elements)} total"
                )
                
                # Send progress update
                progress_msg = {
                    "type": "progress",
                    "current": i + 1,
                    "total": total_tiles,
                    "elements_count": len(all_elements)
                }
                yield json_module.dumps(progress_msg) + "\n"
                
                # Brief delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            # Build GeoJSON from all elements
            data = {
                "version": 0.6,
                "generator": "fetch_road_graph",
                "elements": all_elements
            }
            
            nodes = {
                el["id"]: el
                for el in all_elements
                if el.get("type") == "node"
            }
            ways = [
                el for el in all_elements
                if el.get("type") == "way"
            ]
            
            features = []
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
                    # Create properties dict with ALL tags + way_id
                    properties = {"way_id": way.get("id")}
                    properties.update(tags)  # Add all OSM tags
                    
                    feature = {
                        "type": "Feature",
                        "properties": properties,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": coords,
                        },
                    }
                    features.append(feature)
            
            geojson = {
                "type": "FeatureCollection",
                "features": features
            }
            
            print(
                f"DEBUG: Built GeoJSON with {len(features)} ways "
                f"from {len(all_elements)} elements"
            )
            
            # Send final result
            result = {
                "type": "complete",
                "geojson": geojson,
                "total_ways": len(features),
                "total_elements": len(all_elements)
            }
            yield json_module.dumps(result) + "\n"
            
            # Save to disk and rebuild graph
            global G, engine
            json_path = os.getenv("OSM_JSON_PATH", "data/osm_data.json")
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            save_json(data, json_path)
            G = build_graph_from_overpass(data)
            engine = SimpleRouteEngine(G)
            print(f"DEBUG: Graph rebuilt with {G.number_of_nodes()} nodes")
            
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            error_msg = {
                "type": "error",
                "message": str(e)
            }
            yield json_module.dumps(error_msg) + "\n"
    
    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson"
    )


@app.post("/osm/cache_region")
async def cache_region(region_name: str):
    """Load specified region OSM data into PostGIS cache.
    
    Region must be defined in configs/regions.py.
    Returns streaming NDJSON progress updates.
    
    Args:
        region_name: Region identifier from config (e.g. 'moscow_oblast')
    """
    from src.data.region_loader import load_region_to_cache
    from fastapi.responses import StreamingResponse
    
    return StreamingResponse(
        load_region_to_cache(region_name),
        media_type="application/x-ndjson"
    )


@app.get("/osm/regions")
def list_regions():
    """List all configured and cached regions."""
    from configs.regions import REGIONS
    from src.data.postgis_manager import PostGISManager
    
    db = PostGISManager()
    cached = db.list_regions()
    
    return {
        'configured': list(REGIONS.keys()),
        'cached': cached
    }


@app.get("/tiles/osm/{z}/{x}/{y}.png")
def proxy_osm_tiles(z: int, x: int, y: int):
    """Proxy OSM raster tiles with PostGIS caching.
    
    Flow:
    1. Check PostGIS cache first (tiles.get_tile)
    2. If miss, fetch from upstream OSM
    3. Save to PostGIS (tiles.insert_tile)
    4. Return tile
    
    This ensures tiles are NEVER re-downloaded.
    """
    from src.data.postgis_manager import PostGISManager
    
    db = PostGISManager()
    
    # Check PostGIS cache first
    tile_data = db.get_tile(z, x, y, source='osm')
    
    if tile_data:
        print(f"DEBUG: Tile cache HIT (PostGIS) for {z}/{x}/{y}")
        return Response(
            content=tile_data,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
                "X-Cache": "HIT-PostGIS",
            },
        )
    
    # Cache miss - fetch from upstream
    try:
        import requests as _req
        host = next(_tile_hosts)
        url = f"https://{host}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        headers = {
            "User-Agent": "Diplom-MapClient/0.1 (+https://example.invalid)",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        print(f"DEBUG: Fetching tile {z}/{x}/{y} from {url}")
        r = _req.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail="Tile fetch failed",
            )
        
        # Save to PostGIS
        db.insert_tile(z, x, y, r.content, source='osm')
        print(f"DEBUG: Tile cached in PostGIS for {z}/{x}/{y}")
        
        return Response(
            content=r.content,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
                "X-Cache": "MISS-PostGIS",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
