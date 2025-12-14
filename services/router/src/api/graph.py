"""Graph update API"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from loguru import logger

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


class GraphUpdateRequest(BaseModel):
    """Request to update graph for specific ways"""
    way_ids: List[int]
    bbox: Optional[tuple[float, float, float, float]] = None


@router.post("/update")
async def update_graph(request: Request, body: GraphUpdateRequest):
    """
    Update routing graph for specific OSM ways.
    
    Called by data-processor after downloading new OSM data.
    """
    try:
        graph_builder = request.app.state.graph_builder
        
        await graph_builder.update_graph_for_ways(
            way_ids=body.way_ids,
            bbox=body.bbox
        )
        
        logger.info(f"Graph updated for {len(body.way_ids)} ways")
        
        return {
            "status": "success",
            "updated_ways": len(body.way_ids)
        }
    except Exception as e:
        logger.error(f"Graph update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild")
async def rebuild_graph(request: Request):
    """
    Rebuild entire routing graph from OSM data.
    
    WARNING: This is a long-running operation (1-2 minutes for 64k ways).
    """
    try:
        graph_builder = request.app.state.graph_builder
        
        await graph_builder.build_graph()
        
        logger.info("Graph rebuilt successfully")
        
        return {"status": "success", "message": "Graph rebuilt"}
    except Exception as e:
        logger.error(f"Graph rebuild failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
