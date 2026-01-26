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

router = APIRouter(prefix="/api/v1/routing", tags=["routing"])

class Point(BaseModel):
    lat: float
    lon: float

class MultiPointRequest(BaseModel):
    waypoints: List[Point]
    priority: int = 0
    k: int = 1 # Number of routes requested

@router.post("/calculate", response_model=RouteResponse)
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
        # K-Shortest Paths mode
        try:
            k_routes = await engine.find_k_routes(nodes[0], nodes[1], k=body.k, priority=body.priority)
            for r in k_routes:
                all_routes_data.append(r)
        except Exception as e:
            logger.error(f"K-routing failed: {e}")
            raise HTTPException(status_code=404, detail=f"Routing failed: {e}")
            
    else:
        # Sequential mode (can only return 1 composite route for now per request structure usually)
        # But if user requested K routes for N points, we might just return the best composite route.
        # Future: Implement cartesian product or K-alternatives for composite.
        
        full_route_segments = []
        total_dist = 0.0
        total_time = 0.0
        all_edge_ids = []
        
        for i in range(len(nodes) - 1):
            start = nodes[i]
            end = nodes[i+1]
            try:
                route_data = await engine.find_route(start, end, priority=body.priority)
                if route_data.segments:
                    for seg in route_data.segments:
                         # Map dict to Model manually if needed, or pass dict if Pydantic allows (it usually does via **seg)
                        segment_model = RouteSegment(
                            edge_id=seg['edge_id'],
                            from_node=seg['from_node'],
                            to_node=seg['to_node'],
                            distance_m=seg['distance_m'],
                            speed_limit=seg['speed_limit'],
                            geometry=json.loads(seg['geometry_json']) if seg.get('geometry_json') else None
                        )
                        full_route_segments.append(segment_model)
                
                total_dist += route_data.total_distance_m
                total_time += route_data.total_cost
                all_edge_ids.extend(route_data.edge_ids)
            except Exception as e:
                logger.error(f"Routing failed for segment {i}: {e}")
                raise HTTPException(status_code=404, detail=f"No route between waypoint {i} and {i+1}")

        # Create composite route
        composite_route = EngineRoute(
             edge_ids=all_edge_ids,
             total_cost=total_time,
             total_distance_m=total_dist,
             algorithm="sequential",
             node_sequence=[], # aggregate if needed
             segments=full_route_segments # logic mismatch but handled below
        )
        # Hack for types since composite_route above is EngineRoute but we need Pydantic logic below
        # Actually let's just use the Pydantic model construction here
        
        final_route = RouteModel(
            route_id=0,
            segments=full_route_segments,
            total_distance_m=total_dist,
            estimated_time_sec=total_time,
            diversity_score=1.0,
            edge_ids=all_edge_ids
        )
        return RouteResponse(routes=[final_route])

    # Convert K-routes (EngineRoute) to Response (RouteModel)
    response_routes = []
    for i, r_data in enumerate(all_routes_data):
        r_segments = []
        if r_data.segments:
            for seg in r_data.segments:
                segment_model = RouteSegment(
                    edge_id=seg['edge_id'],
                    from_node=seg['from_node'],
                    to_node=seg['to_node'],
                    distance_m=seg['distance_m'],
                    speed_limit=seg['speed_limit'],
                    geometry=json.loads(seg['geometry_json']) if seg.get('geometry_json') else None
                )
                r_segments.append(segment_model)
        
        response_routes.append(RouteModel(
            route_id=i,
            segments=r_segments,
            total_distance_m=r_data.total_distance_m,
            estimated_time_sec=r_data.total_cost,
            diversity_score=1.0, # TODO calculate
            edge_ids=r_data.edge_ids
        ))
        
    return RouteResponse(routes=response_routes)

    # 3. Construct response
    final_route = RouteModel(
        route_id=0,
        segments=full_route_segments,
        total_distance_m=total_dist,
        estimated_time_sec=total_time,
        diversity_score=1.0, # Not applicable for single route
        edge_ids=all_edge_ids
    )
    
    return RouteResponse(routes=[final_route])
