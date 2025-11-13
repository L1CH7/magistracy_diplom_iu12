from __future__ import annotations

import os
import time
from typing import List, Dict, Any, Tuple
from itertools import cycle

import networkx as nx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.data.graph_builder import build_graph_from_overpass, nearest_node
from src.data.osm_loader import fetch_osm, save_json
from src.routing.simple_engine import SimpleRouteEngine
from src.routing.graph import Graph
from src.routing.route_builder import build_routes
from src.data.postgis_manager import PostGISManager
from src.simulation.agent import SimulationAgent
from loguru import logger as log

app = FastAPI(title="Coordinator Server")


# Logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with unified format."""
    start_time = time.time()
    
    response = await call_next(request)
    
    duration_ms = (time.time() - start_time) * 1000
    log.info(
        "HTTP request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=f"{duration_ms:.1f}",
    )
    
    return response


# Add CORS middleware to allow browser access from client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Point(BaseModel):
    lat: float
    lon: float


class RouteRequest(BaseModel):
    points: List[Point] = Field(
        ...,
        min_length=2,
        description="List of points (lat, lon) where first=from, last=to"
    )
    k: int = Field(5, ge=1, le=10, description="Number of best routes")
    snap_k: int = Field(
        5,
        ge=1,
        le=10,
        description="Number of nearest nodes to consider when snapping"
    )


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


class SimAgentStartRequest(BaseModel):
    """Request to start simulation agent."""
    route_id: int  # ID of selected route
    sim_speed: float = Field(1.0, ge=1.0, le=100.0)


class SimAgentPositionResponse(BaseModel):
    """Agent position at current simulation time."""
    agent_id: int
    position: Dict[str, float]  # {lon, lat, bearing_degrees}
    speed_kmh: float
    eta_seconds: float
    state: str  # moving, stopped, waiting, etc
    is_finished: bool
    assigned_route_id: int = None  # Agent's current route (for visualization)


class OsmLoadRequest(BaseModel):
    bbox: List[float] = Field(
        ..., min_items=4, max_items=4
    )  # [min_lon, min_lat, max_lon, max_lat]


G: nx.MultiDiGraph | None = None
engine: SimpleRouteEngine | None = None
cached_graph: 'Graph' | None = None  # Custom Graph for k-routing
agents: Dict[int, Dict] = {}
route_cache: Dict[str, RouteResponse] = {}
next_agent_id = 1

# Simulation agents storage
sim_agents: Dict[int, 'SimulationAgent'] = {}  # agent_id -> SimulationAgent
# agent_id -> route_data (edges, coords, distance)
sim_routes: Dict[int, Dict] = {}
# agent_id -> selected_route_id (from client)
sim_selected_routes: Dict[int, int] = {}
next_sim_agent_id = 1
next_route_id = 0  # Global unique route ID counter
_tile_hosts = cycle(["a", "b", "c"])  # for upstream OSM subdomains


def calculate_eta_seconds(
    agent: 'SimulationAgent',
    route_data: dict,
    graph,
    current_edge_id: int = None,
    edge_progress: float = None
) -> float:
    """
    Calculate ETA (remaining time) from current position to route end.
    
    If current_edge_id and edge_progress provided: calculates from that position.
    Otherwise: uses agent's current position from agent.current_edge_index/progress.
    
    Algorithm:
    1. If at start (progress=0): return total_time_sec from route_data
    2. Calculate remaining distance based on current progress
    3. Apply congestion factor to each remaining edge
    4. Return time in SIMULATION seconds (not real-time)
    
    Args:
        agent: SimulationAgent with current position
        route_data: Route dict with 'edges', 'total_time_sec', 'total_distance_m'
        graph: Graph instance for edge speed limits
        current_edge_id: Optional explicit edge ID (for prediction)
        edge_progress: Optional explicit progress on edge [0.0-1.0]
        
    Returns:
        ETA in simulation seconds
    """
    # Use explicit position if provided, otherwise agent's current
    total_time_sec = route_data.get('total_time_sec', 0.0)
    
    # If at start (progress=0), return full route time
    overall_progress = agent.current_progress
    
    print(f"ETA_CALC: agent={agent.agent_id}, progress={overall_progress:.3f}, total_time={total_time_sec}, sim_speed={agent.sim_speed}", flush=True)
    
    if overall_progress <= 0.01:  # Within 1% of start
        eta = total_time_sec  # Return REAL-TIME eta (not sim-time)
        print(f"ETA_AT_START: eta={eta:.2f} sec", flush=True)
        return eta
    
    # If finished
    if overall_progress >= 0.99:
        print("ETA_FINISHED: returning 0", flush=True)
        return 0.0
    
    # Calculate remaining time based on progress
    # Simple approach: remaining_time = total_time * (1 - progress)
    # TODO: Add congestion factor per edge
    remaining_fraction = 1.0 - overall_progress
    eta_real_time = total_time_sec * remaining_fraction
    
    print(f"ETA_RESULT: remaining={remaining_fraction:.3f}, eta={eta_real_time:.2f} sec", flush=True)
    
    return eta_real_time


def _project_point_on_segment(
    point: Tuple[float, float],
    seg_start: Tuple[float, float],
    seg_end: Tuple[float, float]
) -> float:
    """
    Project point onto line segment and return fraction [0, 1].
    
    Args:
        point: (lon, lat) to project
        seg_start: (lon, lat) segment start
        seg_end: (lon, lat) segment end
        
    Returns:
        Fraction along segment [0, 1] where projection falls
    """
    px, py = point
    ax, ay = seg_start
    bx, by = seg_end
    
    # Vector from A to B
    dx = bx - ax
    dy = by - ay
    
    # Vector from A to P
    apx = px - ax
    apy = py - ay
    
    # Squared length of segment
    len_sq = dx * dx + dy * dy
    
    if len_sq < 1e-10:
        return 0.0
    
    # Dot product / length squared = projection fraction
    t = (apx * dx + apy * dy) / len_sq
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, t))


def _load_graph() -> nx.MultiDiGraph:
    """Load graph from PostgreSQL (preferred) or JSON fallback."""
    # Try PostgreSQL first
    try:
        from src.data.postgis_manager import PostGISManager
        from src.data.graph_builder import load_graph_from_postgis
        
        db = PostGISManager()
        graph = load_graph_from_postgis(db)
        log.info(
            "graph_loaded_from_postgres",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges()
        )
        return graph
    except Exception as e:
        log.warning("Failed to load from PostgreSQL", error=str(e))
        log.info("Falling back to JSON cache")
    
    # Fallback to JSON
    json_path = os.getenv("OSM_JSON_PATH", "data/osm_data.json")
    if os.path.exists(json_path):
        try:
            log.info("Loading graph from JSON cache", path=json_path)
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            graph = build_graph_from_overpass(data)
            log.info(
                "OSM graph loaded from JSON",
                nodes=graph.number_of_nodes(),
                edges=graph.number_of_edges()
            )
            return graph
        except Exception as e:
            log.warning("Failed to load OSM graph from JSON", error=str(e))
    
    # Demo graph fallback
    log.info("Using demo graph (no PostgreSQL or OSM data)")
    demo = nx.MultiDiGraph()
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
    global G, engine, cached_graph, sim_agents, sim_routes
    try:
        # Clear simulation state on restart
        sim_agents.clear()
        sim_routes.clear()
        sim_selected_routes.clear()
        log.info("Simulation state cleared on startup")
        
        G = _load_graph()
        log.info("Graph loaded for routing", nodes=G.number_of_nodes())
        engine = SimpleRouteEngine(G)
        log.info("Route engine initialized")
        
        # Load custom Graph for k-routing
        from src.data.postgis_manager import PostGISManager
        from src.routing.graph import Graph
        db = PostGISManager()
        cached_graph = Graph.load_from_db(db)
        log.info("Custom graph cached", **cached_graph.get_stats())
    except Exception as e:
        log.error("Startup failed", error=str(e), exc_info=True)
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


@app.post("/routes", response_model=RouteResponse)
def post_routes(req: RouteRequest) -> RouteResponse:
    """
    Build K best routes through multiple points (from → via → to).

    Args:
        req: RouteRequest with points array, k, snap_k

    Returns:
        RouteResponse with routes array and selected index
    """
    # Note: We do NOT clear sim_agents here anymore.
    # Agent persists across route changes.
    # Only client-side _on_points_changed() deletes agent.
    
    # Generate cache key from all points
    points_str = "_".join(
        f"{p.lat:.6f},{p.lon:.6f}" for p in req.points
    )
    cache_key = f"{points_str}_{req.k}_{req.snap_k}"

    if cache_key in route_cache:
        log.debug("Route cache hit", cache_key=cache_key)
        return route_cache[cache_key]

    log.info(
        "Building routes",
        num_points=len(req.points),
        k=req.k,
        snap_k=req.snap_k
    )

    # Use cached graph
    global cached_graph
    if cached_graph is None:
        log.error("Cached graph not loaded")
        raise HTTPException(
            status_code=500,
            detail="Graph not initialized"
        )
    graph = cached_graph

    # Convert points to tuples
    points_tuples = [(p.lat, p.lon) for p in req.points]

    # Build routes
    try:
        routes = build_routes(
            graph,
            points_tuples,
            k=req.k,
            snap_k=req.snap_k
        )
    except Exception as e:
        log.error("Failed to build routes", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build routes: {str(e)}"
        )

    if not routes:
        log.warning(
            "No routes found",
            num_points=len(points_tuples),
            points=points_tuples,
            k=req.k,
            snap_k=req.snap_k
        )
        raise HTTPException(
            status_code=404,
            detail="No path found between selected points. "
                   "Try selecting points closer together or on connected roads."
        )

    # Convert to response format with GLOBAL unique route IDs
    global next_route_id
    routes_data = []
    for route in routes:
        # Assign globally unique route_id
        route.id = next_route_id
        next_route_id += 1
        
        routes_data.append({
            "id": route.id,
            "edges": route.edge_ids,
            "total_distance_m": route.total_distance_m,
            "total_time_sec": route.total_time_sec,
            "geometry": route.geometry,  # List[(lon, lat)]
        })

    response = RouteResponse(routes=routes_data)
    route_cache[cache_key] = response

    log.info(
        "Routes built successfully",
        num_routes=len(routes),
        best_time_sec=routes[0].total_time_sec,
        best_distance_m=routes[0].total_distance_m
    )

    return response


@app.post("/routes/clear_cache")
def clear_route_cache() -> dict:
    """Clear route cache (called when user changes points)."""
    global route_cache, sim_agents, sim_routes
    
    num_cached = len(route_cache)
    num_agents = len(sim_agents)
    
    # Clear route cache
    route_cache.clear()
    
    # Delete all agents (routes no longer valid)
    sim_agents.clear()
    sim_routes.clear()
    
    log.info(
        "Route cache and agents cleared",
        num_routes_cleared=num_cached,
        num_agents_cleared=num_agents
    )
    
    return {
        "status": "cleared",
        "num_routes": num_cached,
        "num_agents": num_agents
    }


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


# ========================================================================
# Simulation Agent Endpoints (новая система)
# ========================================================================

@app.post("/sim/agent/start")
def sim_agent_start(req: SimAgentStartRequest) -> SimAgentPositionResponse:
    """Start simulation agent on selected route."""
    global next_sim_agent_id, route_cache
    
    if cached_graph is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    
    # Find route in cache (simple lookup by route_id)
    route_data = None
    for cached_response in route_cache.values():
        for route in cached_response.routes:
            if route['id'] == req.route_id:
                route_data = route
                log.info(
                    "route_found_in_cache",
                    route_id=req.route_id,
                    route_edges=route['edges'][:3],  # First 3 edges
                    total_edges=len(route['edges'])
                )
                break
        if route_data:
            break
    
    if not route_data:
        raise HTTPException(
            status_code=404,
            detail=f"Route {req.route_id} not found in cache"
        )
    
    # Create simulation agent
    agent_id = next_sim_agent_id
    next_sim_agent_id += 1
    
    # Create agent with route reference (not snapshot)
    agent = SimulationAgent(
        agent_id=agent_id,
        assigned_route_id=req.route_id,
        sim_speed=req.sim_speed
    )
    
    # CRITICAL: Set start_time to NOW (not at object creation!)
    # This ensures agent starts from beginning when client first polls
    agent.start_time = time.time()
    
    sim_agents[agent_id] = agent
    sim_routes[agent_id] = route_data
    
    # Get initial position
    lon, lat, bearing, current_speed, edge_id = agent.get_current_position(
        route_data=route_data,
        elapsed_time_sec=0.0,
        graph=cached_graph
    )
    
    # Convert m/s to km/h
    speed_kmh = current_speed * 3.6
    
    log.info(
        "Simulation agent started",
        agent_id=agent_id,
        route_id=req.route_id,
        sim_speed=req.sim_speed,
        distance_m=route_data['total_distance_m']
    )
    
    return SimAgentPositionResponse(
        agent_id=agent_id,
        position={"lon": lon, "lat": lat, "bearing_degrees": bearing},
        speed_kmh=speed_kmh,
        eta_seconds=route_data['total_time_sec'] / req.sim_speed,
        state="Moving",
        is_finished=False,
        assigned_route_id=agent.assigned_route_id
    )


@app.get("/sim/agent/{agent_id}/position")
def sim_agent_position(agent_id: int) -> SimAgentPositionResponse:
    """Get current agent position."""
    agent = sim_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    route_data = sim_routes.get(agent_id)
    if not route_data:
        raise HTTPException(status_code=500, detail="Route data lost")
    
    # CRITICAL: Verify route consistency
    stored_route_id = route_data.get('id')
    if stored_route_id != agent.assigned_route_id:
        log.error(
            "route_mismatch_detected",
            agent_id=agent_id,
            assigned_route_id=agent.assigned_route_id,
            stored_route_id=stored_route_id
        )
        # Try to find correct route in cache
        correct_route = None
        for cached_response in route_cache.values():
            for route in cached_response.routes:
                if route['id'] == agent.assigned_route_id:
                    correct_route = route
                    sim_routes[agent_id] = route
                    log.info(
                        "route_corrected",
                        agent_id=agent_id,
                        route_id=agent.assigned_route_id
                    )
                    route_data = route
                    break
            if correct_route:
                break
        
        if not correct_route:
            log.error("cannot_find_assigned_route", agent_id=agent_id)
    
    # Only log every 30th request to avoid spam
    if agent_id % 30 == 0 or agent.current_progress > 0.95:
        log.info(
            "position_request",
            agent_id=agent_id,
            assigned_route_id=agent.assigned_route_id,
            stored_route_id=route_data.get('id', 'MISSING'),
            progress=f"{agent.current_progress:.2f}"
        )
    
    # Calculate elapsed time
    elapsed_time = time.time() - agent.start_time
    
    # AUTO-SWITCH LOGIC: Check if agent can switch to selected route
    selected_route_id = sim_selected_routes.get(agent_id)
    if (selected_route_id is not None and
            selected_route_id != agent.assigned_route_id):
        log.info(
            "route_switch_requested",
            agent_id=agent_id,
            current_route_id=agent.assigned_route_id,
            selected_route_id=selected_route_id,
            agent_edge_idx=agent.current_edge_index,
            agent_progress=round(agent.current_progress, 3)
        )
        
        # Find selected route in cache
        selected_route_data = None
        for cached_response in route_cache.values():
            for route in cached_response.routes:
                if route['id'] == selected_route_id:
                    selected_route_data = route
                    break
            if selected_route_data:
                break
        
        if selected_route_data:
            # Check if agent can switch using PostGIS
            current_edges = route_data.get('edges', [])
            new_edges = selected_route_data.get('edges', [])
            
            # Get remaining edges from current position
            remaining_edges = current_edges[agent.current_edge_index:]
            
            if not new_edges:
                log.warning(
                    "cannot_switch_no_new_edges",
                    agent_id=agent_id,
                    new_edges=len(new_edges)
                )
            elif not remaining_edges:
                # Agent finished current route - start new route
                log.info(
                    "switch_to_new_route_from_end",
                    agent_id=agent_id,
                    old_route_finished=True,
                    new_route_id=selected_route_id
                )
                
                # Start new route from beginning
                agent.assigned_route_id = selected_route_id
                sim_routes[agent_id] = selected_route_data
                route_data = selected_route_data
                
                # Reset agent to start of new route
                old_start_time = agent.start_time
                agent.start_time = time.time()
                agent.current_edge_index = 0
                agent.current_edge_progress = 0.0
                agent.current_progress = 0.0
                agent.is_running = True
                agent.final_position = (0.0, 0.0, 0.0, 0)
                
                log.warning(
                    "agent_RESTARTED_on_new_route",
                    agent_id=agent_id,
                    old_route=agent.assigned_route_id,
                    new_route=selected_route_id,
                    old_start_time=round(old_start_time, 2),
                    new_start_time=round(agent.start_time, 2),
                    time_diff=round(agent.start_time - old_start_time, 2),
                    reason="remaining_edges_empty"
                )
                
                # Clear selected route
                del sim_selected_routes[agent_id]
            else:
                # Calculate agent's position in 5 seconds (lookahead)
                max_speed = agent.params.max_speed
                sim_speed = agent.sim_speed
                lookahead_distance = 5.0 * max_speed * sim_speed  # meters
                
                # Find edges agent will be on in 5 seconds
                distance_covered = 0.0
                lookahead_edge_idx = agent.current_edge_index
                
                for i in range(agent.current_edge_index, len(current_edges)):
                    edge_id = current_edges[i]
                    edge = cached_graph.get_edge(edge_id)
                    if not edge:
                        break
                    
                    if i == agent.current_edge_index:
                        # Start from current progress
                        remaining_in_edge = (
                            (1.0 - agent.current_edge_progress) *
                            edge.length_m
                        )
                    else:
                        remaining_in_edge = edge.length_m
                    
                    if (distance_covered + remaining_in_edge >=
                            lookahead_distance):
                        lookahead_edge_idx = i
                        break
                    
                    distance_covered += remaining_in_edge
                
                # Check intersection from lookahead position
                remaining_from_lookahead = current_edges[lookahead_edge_idx:]
                
                log.info(
                    "lookahead_check",
                    agent_id=agent_id,
                    current_idx=agent.current_edge_index,
                    lookahead_idx=lookahead_edge_idx,
                    lookahead_distance_m=lookahead_distance,
                    remaining_edges=len(remaining_from_lookahead)
                )
                
                # Find all common edges (intersecting set)
                intersecting_edges = [
                    edge_id for edge_id in remaining_from_lookahead
                    if edge_id in new_edges
                ]
                
                if not intersecting_edges:
                    log.warning(
                        "cannot_switch_no_intersection",
                        agent_id=agent_id,
                        current_route=agent.assigned_route_id,
                        selected_route=selected_route_id,
                        remaining_edges=len(remaining_edges),
                        new_edges=len(new_edges)
                    )
                else:
                    # Found intersection! Build merged route
                    first_intersect = intersecting_edges[0]
                    last_intersect = intersecting_edges[-1]
                    
                    # pre_intersecting: from current pos to intersection
                    pre_idx = agent.current_edge_index
                    intersect_idx = current_edges.index(first_intersect)
                    pre_intersecting = current_edges[pre_idx:intersect_idx]
                    
                    # post_intersecting: after intersection on new route
                    new_intersect_idx = new_edges.index(last_intersect)
                    post_intersecting = new_edges[new_intersect_idx + 1:]
                    
                    # Merged route
                    merged_edges = (
                        pre_intersecting +
                        intersecting_edges +
                        post_intersecting
                    )
                    
                    log.info(
                        "route_merge",
                        agent_id=agent_id,
                        pre=len(pre_intersecting),
                        intersecting=len(intersecting_edges),
                        post=len(post_intersecting),
                        total=len(merged_edges)
                    )
                    
                    # Build merged route geometry
                    # Get coordinates for each edge from graph
                    merged_coords = []
                    merged_distance = 0.0
                    
                    for edge_id in merged_edges:
                        edge = cached_graph.get_edge(edge_id)
                        if edge and edge.geometry:
                            # Add edge coords (skip first if overlaps prev)
                            if (merged_coords and
                                    edge.geometry[0] == merged_coords[-1]):
                                merged_coords.extend(edge.geometry[1:])
                            else:
                                merged_coords.extend(edge.geometry)
                            merged_distance += edge.length_m
                    
                    # Create merged route data
                    merged_route_data = {
                        'id': selected_route_id,  # Keep new route ID
                        'edges': merged_edges,
                        'geometry': merged_coords,
                        'total_distance_m': merged_distance,
                        'total_time_sec': selected_route_data.get(
                            'total_time_sec', merged_distance / 13.89
                        )
                    }
                    
                    log.info(
                        "auto_switch_merged_route",
                        agent_id=agent_id,
                        old_route_id=agent.assigned_route_id,
                        new_route_id=selected_route_id,
                        merged_edges=len(merged_edges),
                        merged_distance_m=merged_distance
                    )
                    
                    # Calculate absolute distance traveled on OLD route
                    elapsed_old = time.time() - agent.start_time
                    distance_traveled_old = (
                        elapsed_old * agent.sim_speed * agent.params.max_speed
                    )
                    
                    log.info(
                        "merge_distance_check",
                        agent_id=agent_id,
                        elapsed_old=elapsed_old,
                        distance_traveled_old=distance_traveled_old,
                        old_total_distance=route_data['total_distance_m'],
                        old_edge_idx=agent.current_edge_index
                    )
                    
                    # Calculate distance to current edge in MERGED route
                    # We need to find where in merged route the agent is
                    curr_edge_id = current_edges[agent.current_edge_index]
                    
                    if curr_edge_id in merged_edges:
                        # Find same edge in merged route
                        new_edge_idx = merged_edges.index(curr_edge_id)
                        
                        # Calculate distance FROM START of merged route
                        # TO START of current edge
                        distance_to_edge_start = 0.0
                        for i in range(new_edge_idx):
                            edge = cached_graph.get_edge(merged_edges[i])
                            if edge:
                                distance_to_edge_start += edge.length_m
                        
                        # Add progress WITHIN current edge
                        curr_edge = cached_graph.get_edge(curr_edge_id)
                        if curr_edge:
                            distance_within_edge = (
                                agent.current_edge_progress *
                                curr_edge.length_m
                            )
                            distance_to_agent = (
                                distance_to_edge_start + distance_within_edge
                            )
                        else:
                            distance_to_agent = distance_to_edge_start
                        
                        # Recalculate start_time so agent stays at
                        # SAME distance
                        # distance_traveled_new = distance_to_agent
                        # elapsed_new * sim_speed * max_speed =
                        # distance_to_agent
                        # elapsed_new = distance_to_agent /
                        # (sim_speed * max_speed)
                        # start_time_new = now - elapsed_new
                        
                        if agent.sim_speed > 0 and agent.params.max_speed > 0:
                            elapsed_new = distance_to_agent / (
                                agent.sim_speed * agent.params.max_speed
                            )
                            agent.start_time = time.time() - elapsed_new
                        
                        # Update edge index to merged route
                        old_edge_idx = agent.current_edge_index
                        agent.current_edge_index = new_edge_idx
                        
                        log.info(
                            "merge_updated_position",
                            agent_id=agent_id,
                            old_idx=old_edge_idx,
                            new_idx=new_edge_idx,
                            edge_id=curr_edge_id,
                            distance_to_agent=distance_to_agent,
                            elapsed_new=elapsed_new,
                            start_time_adjusted=True
                        )
                    else:
                        # Current edge not in merged route
                        # This shouldn't happen if merge is correct
                        log.error(
                            "merge_error_edge_not_found",
                            agent_id=agent_id,
                            current_edge=curr_edge_id,
                            merged_edges=merged_edges[:5]
                        )
                        # FATAL: Cannot merge, restart instead
                        log.error(
                            "FATAL_merge_failed_restarting_agent",
                            agent_id=agent_id,
                            current_route=agent.assigned_route_id,
                            selected_route=selected_route_id
                        )
                        # Force restart
                        agent.start_time = time.time()
                        agent.current_edge_index = 0
                        agent.current_edge_progress = 0.0
                        agent.current_progress = 0.0
                    
                    # Switch to merged route
                    old_route_id = agent.assigned_route_id
                    agent.assigned_route_id = selected_route_id
                    sim_routes[agent_id] = merged_route_data
                    route_data = merged_route_data
                    
                    log.info(
                        "route_switched_to_merged",
                        agent_id=agent_id,
                        old_route=old_route_id,
                        new_route=selected_route_id,
                        merged_edges=len(merged_edges)
                    )
                    
                    # Clear selected route (already assigned)
                    del sim_selected_routes[agent_id]
    # Agent movement is ASYNC - based purely on elapsed_time
    # Route changes don't affect current position/speed
    lon, lat, bearing, current_speed, edge_id = agent.get_current_position(
        route_data=route_data,
        elapsed_time_sec=elapsed_time,
        graph=cached_graph
    )
    
    # Convert m/s to km/h
    speed_kmh = current_speed * 3.6
    
    # Calculate DYNAMIC ETA by analyzing remaining edges
    sim_time_remaining = calculate_eta_seconds(agent, route_data, cached_graph)
    
    return SimAgentPositionResponse(
        agent_id=agent_id,
        position={"lon": lon, "lat": lat, "bearing_degrees": bearing},
        speed_kmh=speed_kmh,
        eta_seconds=sim_time_remaining,
        state="Moving" if agent.is_running else "Stopped",
        is_finished=agent.current_progress >= 1.0,
        assigned_route_id=agent.assigned_route_id
    )


@app.post("/sim/agent/{agent_id}/stop")
def sim_agent_stop(agent_id: int) -> dict:
    """Stop simulation agent."""
    agent = sim_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent.stop()
    log.info("Agent stopped", agent_id=agent_id)
    
    return {"status": "stopped"}


class SimAgentRestartRequest(BaseModel):
    """Request to restart agent with optional route change."""
    route_id: int = None  # Optional: switch to new route before restart
    sim_speed: float = None  # Optional: change simulation speed


@app.post("/sim/agent/{agent_id}/restart")
def sim_agent_restart(
    agent_id: int,
    req: SimAgentRestartRequest = None
) -> SimAgentPositionResponse:
    """Restart simulation agent from beginning, optionally with new route."""
    agent = sim_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    route_data = sim_routes.get(agent_id)
    if not route_data:
        raise HTTPException(status_code=500, detail="Route data lost")
    
    # If route_id provided, switch to new route
    if req and req.route_id is not None:
        # Find new route in cache
        new_route_data = None
        for cached_response in route_cache.values():
            for route in cached_response.routes:
                if route['id'] == req.route_id:
                    new_route_data = route
                    break
            if new_route_data:
                break
        
        if not new_route_data:
            raise HTTPException(
                status_code=404,
                detail=f"Route {req.route_id} not found in cache"
            )
        
        # Update agent's route reference AND stored route
        agent.assigned_route_id = req.route_id
        sim_routes[agent_id] = new_route_data
        route_data = new_route_data  # Update local var for use below
        
        log.info(
            "agent_route_changed_on_restart",
            agent_id=agent_id,
            new_route_id=req.route_id,
            new_edges_count=len(new_route_data['edges'])
        )
    
    # Update sim_speed if provided
    if req and req.sim_speed is not None:
        agent.sim_speed = req.sim_speed
    
    log.info(
        "before_agent_restart",
        agent_id=agent_id,
        current_edge_index=agent.current_edge_index,
        current_progress=agent.current_progress
    )
    
    # CRITICAL: Reset agent to beginning of (possibly new) route
    agent.restart()
    
    log.info(
        "after_agent_restart",
        agent_id=agent_id,
        current_edge_index=agent.current_edge_index,
        current_progress=agent.current_progress
    )
    
    # Get initial position with (possibly updated) route data
    lon, lat, bearing, current_speed, edge_id = agent.get_current_position(
        route_data=route_data,
        elapsed_time_sec=0.0,
        graph=cached_graph
    )
    
    # Convert m/s to km/h
    speed_kmh = current_speed * 3.6
    
    # Calculate dynamic ETA
    sim_time_remaining = calculate_eta_seconds(agent, route_data, cached_graph)
    
    log.info("Agent restarted", agent_id=agent_id)
    
    return SimAgentPositionResponse(
        agent_id=agent_id,
        position={"lon": lon, "lat": lat, "bearing_degrees": bearing},
        speed_kmh=speed_kmh,
        eta_seconds=sim_time_remaining,
        state="Moving",
        is_finished=False,
        assigned_route_id=agent.assigned_route_id
    )


@app.post("/sim/agent/{agent_id}/consider_route")
def sim_agent_consider_route(agent_id: int, route_id: int) -> dict:
    """
    Set selected route for agent (blue route on map).
    Agent will auto-switch if it can reach the route.
    
    Args:
        agent_id: Agent ID
        route_id: Route ID to consider
        
    Returns:
        Status dict
    """
    agent = sim_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Store selected route
    sim_selected_routes[agent_id] = route_id
    log.info(
        "agent_considering_route",
        agent_id=agent_id,
        route_id=route_id,
        assigned_route_id=agent.assigned_route_id
    )
    
    return {"status": "ok", "selected_route_id": route_id}


@app.post("/sim/agent/{agent_id}/reroute")
def sim_agent_reroute(
    agent_id: int,
    req: SimAgentStartRequest
) -> SimAgentPositionResponse:
    """
    Mid-route rerouting: Change agent's route without restarting.
    
    Agent checks if current position is on ANY edge of new route:
    - If YES: continues on new route from current position
    - If NO: continues on old route (ignores reroute request)
    """
    global cached_graph
    
    agent = sim_agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    old_route_data = sim_routes.get(agent_id)
    if not old_route_data:
        raise HTTPException(status_code=500, detail="Route data lost")
    
    if cached_graph is None:
        raise HTTPException(status_code=500, detail="Graph not loaded")
    
    # Find new route in cache
    new_route_data = None
    for cached_response in route_cache.values():
        for route in cached_response.routes:
            if route['id'] == req.route_id:
                new_route_data = route
                break
        if new_route_data:
            break
    
    if not new_route_data:
        raise HTTPException(
            status_code=404,
            detail=f"Route {req.route_id} not found in cache"
        )
    
    # Get current position on old route
    elapsed_time = time.time() - agent.start_time
    lon, lat, bearing, current_speed, old_edge_id = agent.get_current_position(
        route_data=old_route_data,
        elapsed_time_sec=elapsed_time,
        graph=cached_graph
    )
    
    # Check if agent can switch to new route (predictive with time margin)
    new_edges = new_route_data['edges']
    old_route_id = agent.assigned_route_id  # Save before updating
    
    # Find if current edge is on new route
    edge_in_new_route = old_edge_id in new_edges
    
    log.info(
        "reroute_attempt",
        agent_id=agent_id,
        old_route_id=old_route_id,
        new_route_id=req.route_id,
        current_edge=old_edge_id,
        edge_in_new_route=edge_in_new_route
    )
    
    # Predictive rerouting: check if agent has time to react
    # TODO: Add time prediction (need 1km @ 100km/h is ok, 100m is not)
    can_reroute = edge_in_new_route
    
    if can_reroute:
        # Agent is on new route! Switch to it
        new_edge_index = new_edges.index(old_edge_id)
        
        # Update agent's route reference
        agent.assigned_route_id = req.route_id
        agent.sim_speed = req.sim_speed
        
        # Calculate new start_time to maintain current position
        # Distance covered on new route up to current edge
        new_coords = new_route_data['geometry']
        segments_covered = new_edge_index
        # Distance from start of new route to current edge
        distance_to_current_edge = agent.current_progress * old_route_data['total_distance_m']
        # Adjust start_time so elapsed_time produces this distance
        adjusted_sim_time = distance_to_current_edge / agent.params.max_speed
        agent.start_time = time.time() - (adjusted_sim_time / agent.sim_speed)
        
        # Update stored route data
        sim_routes[agent_id] = new_route_data
        
        log.info(
            "agent_rerouted_success",
            agent_id=agent_id,
            old_route_id=old_route_id,
            new_route_id=req.route_id,
            current_edge=old_edge_id,
            new_edge_index=new_edge_index,
            old_edges_count=len(old_route_data['edges']),
            new_edges_count=len(new_route_data['edges'])
        )
    else:
        # Agent NOT on new route - continue on old route (ignore reroute)
        log.info(
            "reroute_ignored",
            agent_id=agent_id,
            current_edge=old_edge_id,
            new_route_id=req.route_id,
            reason="agent_not_on_new_route"
        )
    
    # Get current position (now with potentially updated route)
    lon, lat, bearing, current_speed, edge_id = agent.get_current_position(
        route_data=sim_routes[agent_id],
        elapsed_time_sec=time.time() - agent.start_time,
        graph=cached_graph
    )
    
    # Convert m/s to km/h
    speed_kmh = current_speed * 3.6
    
    # Calculate dynamic ETA
    sim_time_remaining = calculate_eta_seconds(
        agent, sim_routes[agent_id], cached_graph
    )
    
    return SimAgentPositionResponse(
        agent_id=agent_id,
        position={"lon": lon, "lat": lat, "bearing_degrees": bearing},
        speed_kmh=speed_kmh,
        eta_seconds=sim_time_remaining,
        state="Moving" if agent.is_running else "Stopped",
        is_finished=agent.current_progress >= 1.0,
        assigned_route_id=agent.assigned_route_id
    )


@app.delete("/sim/agent/{agent_id}")
def sim_agent_delete(agent_id: int) -> dict:
    """Delete simulation agent."""
    if agent_id in sim_agents:
        del sim_agents[agent_id]
    if agent_id in sim_routes:
        del sim_routes[agent_id]
    
    log.info("Agent deleted", agent_id=agent_id)
    
    return {"status": "deleted"}


@app.get("/graph")
def get_graph():
    """Get full graph from PostgreSQL.
    
    Returns nodes and edges with all attributes.
    For large graphs, consider using bbox-filtered query instead.
    """
    try:
        db = PostGISManager()
        nodes, edges = db.load_full_graph()
        
        log.info(
            "Graph loaded from DB",
            nodes=len(nodes),
            edges=len(edges)
        )
        
        return {
            'nodes': nodes,
            'edges': edges,
            'stats': db.get_graph_stats()
        }
    except Exception as e:
        log.error("Graph load failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load graph from DB: {str(e)}"
        )


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
    from src.data.osm_overpass import fetch_overpass, build_highway_query
    import asyncio
    from fastapi.responses import StreamingResponse
    import json as json_module
    
    min_lon, min_lat, max_lon, max_lat = req.bbox
    bbox_tuple = (min_lon, min_lat, max_lon, max_lat)
    
    db = PostGISManager()
    
    async def generate():
        # LAYER 1: Try processed GeoJSON cache (fastest)
        try:
            from src.server.road_styling import filter_geojson
            
            log.info(f"Fetching road graph for bbox={bbox_tuple}")
            
            # Check processed cache first
            processed_geojson = db.get_processed_geojson(
                bbox_tuple,
                style_version='v1'
            )
            
            if processed_geojson and processed_geojson.get('features'):
                # Processed cache HIT - instant response!
                feature_count = len(processed_geojson['features'])
                log.info(
                    f"Processed GeoJSON cache HIT: "
                    f"bbox={bbox_tuple} features={feature_count}"
                )
                yield json_module.dumps({
                    'type': 'info',
                    'message': 'Loaded from processed cache (instant)',
                }) + '\n'
                
                yield json_module.dumps({
                    'type': 'complete',
                    'cached': True,
                    'processed': True,
                    'geojson': processed_geojson,
                    'total_ways': feature_count,
                    'bbox': list(bbox_tuple),
                }) + '\n'
                return
            
            # LAYER 2: Try raw OSM cache (need to process)
            geojson = db.get_roads_geojson(bbox_tuple)
            
            if geojson and geojson.get('features'):
                # Raw cache HIT - need to filter + classify
                feature_count = len(geojson['features'])
                log.info(
                    f"Raw OSM cache HIT: bbox={bbox_tuple} "
                    f"features={feature_count}, will process"
                )
                yield json_module.dumps({
                    'type': 'info',
                    'message': 'Processing cached OSM data...',
                }) + '\n'
                
                # Filter GeoJSON server-side (только фильтрация)
                filtered_geojson = filter_geojson(
                    geojson,
                    drivable_only=True
                )
                
                # Save to processed cache for next time
                db.save_processed_geojson(
                    bbox_tuple,
                    filtered_geojson,
                    style_version='v1'
                )
                
                filtered_count = len(filtered_geojson['features'])
                log.info(
                    f"OSM data filtered: "
                    f"{feature_count} → {filtered_count} drivable roads"
                )
                
                yield json_module.dumps({
                    'type': 'complete',
                    'cached': True,
                    'processed': True,
                    'geojson': filtered_geojson,
                    'total_ways': filtered_count,
                    'bbox': list(bbox_tuple),
                }) + '\n'
                return
            else:
                log.info(
                    f"OSM Cache MISS: bbox={bbox_tuple}, "
                    f"will fetch from Overpass"
                )
        except Exception as e:
            log.error(f"PostGIS cache check FAILED: {e}")
        
        # LAYER 3: Cache miss - fetch from Overpass
        log.info(f"Fetching from Overpass: bbox={bbox_tuple}")
        
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
        log.info(f"Calculated {total_tiles} tiles for Overpass fetch")
        
        # Collect all elements
        all_elements = []
        seen_ids = set()
        
        try:
            for i, tile_bbox in enumerate(tiles):
                log.debug(f"Fetching tile {i+1}/{total_tiles}")
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
                
                log.debug(
                    "Tile fetched",
                    current=i+1,
                    total=total_tiles,
                    raw=len(elements),
                    new=new_count,
                    accumulated=len(all_elements)
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
            
            # Save to PostGIS database FIRST
            try:
                log.info(f"Saving {len(features)} ways to PostGIS...")
                way_list = []
                for feature in features:
                    props = feature.get("properties", {})
                    geom = feature.get("geometry", {})
                    way_id = props.get("way_id")
                    coords = geom.get("coordinates", [])
                    
                    # Extract tags (all properties except way_id)
                    tags = {k: v for k, v in props.items() if k != "way_id"}
                    
                    if way_id and len(coords) >= 2:
                        way_list.append((way_id, coords, tags))
                
                if way_list:
                    db.bulk_insert_ways(way_list)
                    log.info(
                        f"Successfully cached {len(way_list)} ways "
                        f"in PostGIS"
                    )
            except Exception as e:
                log.error(f"Failed to save ways to PostGIS: {e}")
            
            # Filter GeoJSON for client (remove non-drivable roads)
            from src.server.road_styling import filter_geojson
            
            filtered_geojson = filter_geojson(
                geojson,
                drivable_only=True
            )
            filtered_count = len(filtered_geojson['features'])
            
            log.info(
                f"Filtered Overpass data: "
                f"{len(features)} → {filtered_count} drivable roads"
            )
            
            # Save filtered GeoJSON to cache
            try:
                db.save_processed_geojson(
                    bbox_tuple,
                    filtered_geojson,
                    style_version='v1'
                )
                log.info(
                    f"Filtered GeoJSON cached for future requests"
                )
            except Exception as e:
                log.error(
                    f"Failed to cache filtered GeoJSON: {e}"
                )
            
            # Send final result (filtered version with all OSM properties)
            result = {
                "type": "complete",
                "cached": False,
                "processed": True,
                "geojson": filtered_geojson,
                "total_ways": filtered_count,
                "total_elements": len(all_elements),
                "bbox": list(bbox_tuple),
            }
            yield json_module.dumps(result) + "\n"
            
            # Rebuild graph ONLY for cache MISS (fresh Overpass data)
            # Graph building is expensive - skip for cached data
            global G, engine
            json_path = os.getenv("OSM_JSON_PATH", "data/osm_data.json")
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            save_json(data, json_path)
            G = build_graph_from_overpass(data)
            engine = SimpleRouteEngine(G)
            log.info(f"Graph rebuilt with {G.number_of_nodes()} nodes")
            
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
    db = PostGISManager()
    
    # Check PostGIS cache first
    tile_data = db.get_tile(z, x, y, source='osm')
    
    if tile_data:
        log.debug("Tile cache HIT", z=z, x=x, y=y, source="PostGIS")
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
        log.debug("Fetching tile from OSM", z=z, x=x, y=y, url=url)
        r = _req.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail="Tile fetch failed",
            )
        
        # Save to PostGIS
        db.insert_tile(z, x, y, r.content, source='osm')
        log.debug("Tile cached", z=z, x=x, y=y, size=len(r.content))
        
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
