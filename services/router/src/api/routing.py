"""
Routing API endpoints.
"""

import json
from typing import List
from fastapi import APIRouter, HTTPException, Request, Depends
from loguru import logger
from pydantic import BaseModel

from ..models import RouteRequest, RouteResponse, Route as RouteModel, RouteSegment
from ..engine.interface import Route as EngineRoute
from .metrics import observe_routing_metrics

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])

class Point(BaseModel):
    lat: float
    lon: float

class MultiPointRequest(BaseModel):
    waypoints: List[Point]
    priority: int = 0
    k: int = 1 # Number of routes requested

@router.post("/calculate", response_model=RouteResponse)
@observe_routing_metrics
async def calculate_route(request: Request, body: MultiPointRequest):
    """
    Calculate route between checkpoints.
    If k > 1 and only 2 points, returns K routes.
    If > 2 points, constructs sequential path (currently single best path per segment).
    """
    if len(body.waypoints) < 2:
        raise HTTPException(status_code=400, detail="At least 2 waypoints required")
    
    engine = request.app.state.routing_engine
    
    # 1. Snap all points to graph nodes
    nodes = []
    
    for pt in body.waypoints:
        snapped = await engine.snap_to_road(pt.lat, pt.lon, snap_radius_m=200.0)
        if not snapped:
            raise HTTPException(status_code=404, detail=f"Could not snap point {pt} to graph")
        nodes.append(snapped[0])
    
    # 2. Logic split: K-paths for 2 points vs Sequential for N points
    all_routes_data = []
    
    if len(nodes) == 2 and body.k > 1:
        # K-Shortest Paths mode (2 points)
        try:
            k_routes = await engine.find_k_routes(nodes[0], nodes[1], k=body.k, priority=body.priority, use_diversity=True)
            for r in k_routes:
                all_routes_data.append(r)
        except Exception as e:
            logger.error(f"K-routing failed: {e}")
            raise HTTPException(status_code=404, detail=f"Routing failed: {e}")
            
    elif len(nodes) > 2 and body.k > 1:
        # K-Shortest Paths mode (Multi-point) - Combinatorial / Beam Search
        try:
            # 1. Fetch K routes for each segment
            segment_options = []
            for i in range(len(nodes) - 1):
                start, end = nodes[i], nodes[i+1]
                routes = await engine.find_k_routes(start, end, k=body.k, priority=body.priority, use_diversity=True)
                if not routes:
                    raise HTTPException(status_code=404, detail=f"No route between waypoint {i} and {i+1}")
                segment_options.append(routes)
            
            # ...Logic for merging segments...
            current_paths = segment_options[0]
            for i in range(1, len(segment_options)):
                next_segment_routes = segment_options[i]
                new_candidates = []
                for path_so_far in current_paths:
                    for extension in next_segment_routes:
                        merged_ids = (path_so_far.edge_ids or []) + (extension.edge_ids or [])
                        merged_segments = (path_so_far.segments or []) + (extension.segments or [])
                        seq_so_far = path_so_far.node_sequence or []
                        seq_ext = extension.node_sequence or []
                        if seq_so_far and seq_ext and seq_so_far[-1] == seq_ext[0]:
                            merged_seq = seq_so_far + seq_ext[1:]
                        else:
                            merged_seq = seq_so_far + seq_ext

                        new_route = EngineRoute(
                            edge_ids=merged_ids,
                            total_cost=path_so_far.total_cost + extension.total_cost,
                            total_distance_m=path_so_far.total_distance_m + extension.total_distance_m,
                            algorithm="sequential_ksp",
                            node_sequence=merged_seq, 
                            segments=merged_segments
                        )
                        new_candidates.append(new_route)
                new_candidates.sort(key=lambda r: r.total_cost)
                current_paths = new_candidates[:body.k]
            all_routes_data = current_paths
            
        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"Multi-point K-routing failed: {e}")
            raise HTTPException(status_code=500, detail=f"Multi-point routing failed: {e}")

    else:
        # Sequential mode (Single route)
        full_route_segments = []
        total_dist = 0.0
        total_time = 0.0
        all_edge_ids = []
        
        for i in range(len(nodes) - 1):
            start = nodes[i]
            end = nodes[i+1]
            try:
                route_data = await engine.find_route(start, end, priority=body.priority)
                if not route_data or not route_data.segments:
                        raise Exception("No segments found")
                        
                for seg in route_data.segments:
                    geom = None
                    if 'geometry_json' in seg and seg['geometry_json']:
                            geom = json.loads(seg['geometry_json']) if isinstance(seg['geometry_json'], str) else seg['geometry_json']

                    segment_model = RouteSegment(
                        edge_id=seg['edge_id'],
                        from_node=seg['from_node'],
                        to_node=seg['to_node'],
                        distance_m=seg['distance_m'],
                        speed_limit=seg['speed_limit'],
                        geometry=geom
                    )
                    full_route_segments.append(segment_model)
                
                total_dist += route_data.total_distance_m
                total_time += route_data.total_cost
                all_edge_ids.extend(route_data.edge_ids)
            except Exception as e:
                logger.error(f"Routing failed for segment {i}: {e}")
                raise HTTPException(status_code=404, detail=f"No route between waypoint {i} and {i+1}")

        # Create composite route
        final_route = RouteModel(
            route_id=0,
            segments=full_route_segments,
            total_distance_m=total_dist,
            estimated_time_sec=total_time,
            diversity_score=1.0,
            edge_ids=all_edge_ids
        )
        response_routes = [final_route]
        return RouteResponse(routes=response_routes)

    # Convert K-routes (EngineRoute) to Response (RouteModel)
    response_routes = []
    for i, r_data in enumerate(all_routes_data):
        r_segments = []
        if r_data.segments:
            for seg in r_data.segments:
                geom = None
                if 'geometry_json' in seg and seg['geometry_json']:
                        geom = json.loads(seg['geometry_json']) if isinstance(seg['geometry_json'], str) else seg['geometry_json']
                
                segment_model = RouteSegment(
                    edge_id=seg['edge_id'],
                    from_node=seg['from_node'],
                    to_node=seg['to_node'],
                    distance_m=seg['distance_m'],
                    speed_limit=seg['speed_limit'],
                    geometry=geom
                )
                r_segments.append(segment_model)
        
        response_routes.append(RouteModel(
            route_id=i,
            segments=r_segments,
            total_distance_m=r_data.total_distance_m,
            estimated_time_sec=r_data.total_cost,
            diversity_score=1.0, # Approximate for combined
            edge_ids=r_data.edge_ids
        ))

    return RouteResponse(routes=response_routes)
