from __future__ import annotations

import os
from typing import List, Dict, Any

import networkx as nx
from fastapi import FastAPI, HTTPException
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


def _load_graph() -> nx.DiGraph:
    json_path = os.getenv("OSM_JSON_PATH")
    if json_path and os.path.exists(json_path):
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return build_graph_from_overpass(data)
    # Demo graph
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
    G = _load_graph()
    engine = SimpleRouteEngine(G)


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
