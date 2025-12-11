"""Routing API - k-shortest paths with pgRouting"""

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple
from loguru import logger
import time

router = APIRouter(prefix="/api/v1/route", tags=["routing"])


class Point(BaseModel):
    """Geographic point (latitude, longitude)"""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")


class RouteRequest(BaseModel):
    """Request for k-shortest routes between points"""
    points: List[Point] = Field(
        ..., min_items=2,
        description="Waypoints (origin, destination, optional via points)"
    )
    k: int = Field(1, ge=1, le=10, description="Number of routes")
    snap_to_edge: bool = Field(True, description="Auto-snap to roads")
    use_diversity: bool = Field(
        False,
        description="Apply diversity filter (False = return all k routes)"
    )


class EdgeGeometry(BaseModel):
    """Edge geometry with properties"""
    edge_id: int
    geometry: dict  # GeoJSON LineString
    highway: str
    name: Optional[str]
    length_m: float
    cost_sec: float


class RouteResponse(BaseModel):
    """Single route result"""
    route_id: int
    edge_ids: List[int]
    edges: List[EdgeGeometry]  # Full geometry for rendering
    total_cost_sec: float
    total_distance_m: float
    total_distance_km: float
    duration_min: float


class RoutingResponse(BaseModel):
    """Response with k alternative routes"""
    routes: List[RouteResponse]
    computation_time_ms: float
    snapped_points: Optional[List[Tuple[int, float]]] = None  # [(node_id, distance_from_input), ...]


@router.post("/find", response_model=RoutingResponse)
async def find_routes(
    request: Request,
    body: RouteRequest
):
    """
    Find k-shortest routes between points.
    
    Process:
    1. If snap_to_edge=True: snap input points to nearest graph nodes
    2. Find k-shortest paths using pgr_KSP (with turn restrictions)
    3. Apply diversity filter if use_diversity=True (default 60% unique edges)
    4. Fetch full edge geometries for rendering
    5. Log computation time to Grafana (optional)
    
    Args:
        body: RouteRequest with points, k, snap_to_edge, use_diversity
    
    Returns:
        RoutingResponse with k routes and computation time
    """
    start_time = time.perf_counter()
    
    try:
        routing_engine = request.app.state.routing_engine
        
        if not routing_engine:
            raise HTTPException(status_code=503, detail="Routing engine not initialized")
        
        # Step 1: Snap to nearest edges (if enabled)
        if body.snap_to_edge:
            logger.debug(f"Snapping {len(body.points)} points to edges")
            snapped_nodes = []
            snapped_info = []

            for point in body.points:
                # Snap to nearest edge
                result = await routing_engine.snap_to_road(
                    lat=point.lat,
                    lon=point.lon,
                    snap_radius_m=500.0
                )
                if result is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No edge near ({point.lat}, {point.lon})"
                    )
                edge_id, position_m = result

                # Get edge info and choose appropriate node
                async with request.app.state.db.pool.acquire() as conn:
                    edge_info = await conn.fetchrow(
                        """
                        SELECT 
                            source, 
                            target, 
                            length_m,
                            cost,
                            reverse_cost,
                            oneway
                        FROM graphs.edges
                        WHERE id = $1
                        """,
                        edge_id
                    )

                # Choose node based on direction
                # For routing: always choose node that allows path continuation
                if edge_info['oneway']:
                    if edge_info['cost'] > 0:
                        # Forward only: always use source
                        # (routing needs to enter edge from beginning)
                        node_id = edge_info['source']
                    else:
                        # Backward only: always use target  
                        # (routing needs to enter from end)
                        node_id = edge_info['target']
                else:
                    # Bidirectional: choose nearest end
                    node_id = (edge_info['source']
                               if position_m < edge_info['length_m'] / 2
                               else edge_info['target'])

                snapped_nodes.append(node_id)
                snapped_info.append((edge_id, position_m))
        else:
            # Points must be node IDs (for testing/debugging)
            snapped_nodes = [int(p.lat) for p in body.points]  # Hack: lat=node_id
            snapped_info = None
            logger.debug(f"Using provided node IDs: {snapped_nodes}")
        
        # Step 2: Route between consecutive waypoints
        all_routes = []
        
        if len(snapped_nodes) == 2:
            # Simple A→B routing
            routes = await routing_engine.find_k_routes(
                start_node=snapped_nodes[0],
                end_node=snapped_nodes[1],
                k=body.k,
                use_diversity=body.use_diversity
            )
            all_routes = routes
        else:
            # Multi-waypoint routing (A→B→C→D...)
            # Build route segments and combine
            segment_routes = []
            
            for i in range(len(snapped_nodes) - 1):
                segment = await routing_engine.find_k_routes(
                    start_node=snapped_nodes[i],
                    end_node=snapped_nodes[i + 1],
                    k=1,  # Only 1 route per segment for multi-waypoint
                    use_diversity=False
                )
                segment_routes.append(segment[0])
            
            # Combine segments into single route
            combined_edges = []
            combined_cost = 0.0
            combined_distance = 0.0
            
            for segment in segment_routes:
                combined_edges.extend(segment.edge_ids)
                combined_cost += segment.total_cost
                combined_distance += segment.total_distance_m
            
            # Create single combined route
            from ..engine.interface import Route, RoutingAlgorithm
            combined_route = Route(
                edge_ids=combined_edges,
                total_cost=combined_cost,
                total_distance_m=combined_distance,
                algorithm=RoutingAlgorithm.PGROUTING.value
            )
            all_routes = [combined_route]
        
        # Step 3: Fetch full geometries for each route
        route_responses = []
        
        for idx, route in enumerate(all_routes):
            edge_geometries = await _fetch_edge_geometries(
                request.app.state.db,
                route.edge_ids,
                route.node_sequence
            )
            
            route_responses.append(RouteResponse(
                route_id=idx + 1,
                edge_ids=route.edge_ids,
                edges=edge_geometries,
                total_cost_sec=route.total_cost,
                total_distance_m=route.total_distance_m,
                total_distance_km=route.total_distance_m / 1000.0,
                duration_min=route.total_cost / 60.0
            ))
        
        # Computation time
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        logger.info(
            f"Found {len(route_responses)} routes in {elapsed_ms:.1f}ms: "
            f"{[r.total_distance_km for r in route_responses]} km"
        )
        
        # TODO: Log to Grafana
        # await log_routing_metrics(
        #     computation_time_ms=elapsed_ms,
        #     num_routes=len(route_responses),
        #     total_edges=sum(len(r.edge_ids) for r in route_responses)
        # )
        
        return RoutingResponse(
            routes=route_responses,
            computation_time_ms=elapsed_ms,
            snapped_points=snapped_info
        )
        
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _fetch_edge_geometries(
    db_pool,
    edge_ids: List[int],
    node_sequence: Optional[List[int]] = None
) -> List[EdgeGeometry]:
    """
    Fetch full edge geometries with properties for rendering.
    Reverses geometry if edge traversed backward.

    Args:
        db_pool: Database connection pool
        edge_ids: List of edge IDs in traversal order
        node_sequence: Node IDs in traversal order (from pgr_dijkstra/pgr_KSP)
                       Format: [node0, node1, node2, ...] where edge[i] connects
                       node[i] to node[i+1]

    Returns:
        List of EdgeGeometry with correctly oriented GeoJSON geometries
    """
    import json

    async with db_pool.acquire() as conn:
        query = """
            SELECT
                id,
                source,
                target,
                ST_AsGeoJSON(geom) as geometry,
                highway,
                name,
                length_m,
                cost
            FROM graphs.edges
            WHERE id = ANY($1)
            ORDER BY array_position($1, id)
        """

        rows = await conn.fetch(query, edge_ids)
        
        result = []
        for idx, row in enumerate(rows):
            geom = json.loads(row['geometry'])
            
            # Determine if edge traversed backward
            # node_sequence: [n0, n1, n2, ...], edge_ids: [e0, e1, ...]
            # edge e0 connects n0→n1, e1 connects n1→n2, etc.
            should_reverse = False
            if node_sequence and len(node_sequence) > idx + 1:
                from_node = node_sequence[idx]
                to_node = node_sequence[idx + 1]
                edge_source = row['source']
                edge_target = row['target']
                
                # Check if edge orientation matches traversal direction
                if edge_source == from_node and edge_target == to_node:
                    # Forward: source→target matches path
                    should_reverse = False
                elif edge_target == from_node and edge_source == to_node:
                    # Backward: target→source matches path
                    should_reverse = True
                else:
                    # Mismatch - log warning but don't reverse
                    logger.warning(
                        f"Edge {row['id']} topology mismatch: "
                        f"edge ({edge_source}→{edge_target}) vs "
                        f"path ({from_node}→{to_node})"
                    )
            
            # Reverse coordinates if needed
            if should_reverse and geom.get('type') == 'LineString':
                geom['coordinates'] = list(reversed(geom['coordinates']))
            
            result.append(EdgeGeometry(
                edge_id=row['id'],
                geometry=geom,
                highway=row['highway'],
                name=row['name'],
                length_m=row['length_m'],
                cost_sec=row['cost']
            ))
        
        return result


@router.get("/snap")
async def snap_point(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: float = Query(500.0, ge=10, le=2000, description="Snap radius")
):
    """
    Snap a geographic point to nearest graph edge.

    Returns edge_id and position along edge (0.0 to length_m).
    Useful for debugging and manual route planning.

    Args:
        lat: Latitude
        lon: Longitude
        radius: Search radius in meters (default 500m)

    Returns:
        {
            edge_id: int,
            position_m: float (distance from edge start),
            distance_m: float (distance from input point to edge),
            edge_info: {highway, name, length_m}
        }
    """
    try:
        routing_engine = request.app.state.routing_engine

        result = await routing_engine.snap_to_road(
            lat=lat,
            lon=lon,
            snap_radius_m=radius
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail="No edge found within radius"
            )

        edge_id, position_m = result

        # Fetch edge info
        async with request.app.state.db.pool.acquire() as conn:
            edge = await conn.fetchrow(
                """
                SELECT
                    highway,
                    name,
                    length_m,
                    ST_Distance(
                        ST_Transform(geom, 3857),
                        ST_Transform(
                            ST_SetSRID(ST_MakePoint($2, $3), 4326),
                            3857
                        )
                    ) as distance_m
                FROM graphs.edges
                WHERE id = $1
                """,
                edge_id, lon, lat
            )

        return {
            "edge_id": edge_id,
            "position_along_edge_m": position_m,
            "snap_distance_m": edge['distance_m'],
            "edge_info": {
                "highway": edge['highway'],
                "name": edge['name'],
                "total_edge_length_m": edge['length_m']
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Snap failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )
