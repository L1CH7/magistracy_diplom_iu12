"""
Graph management API endpoints.
"""

import asyncio
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from loguru import logger

from ..state.task_manager import task_manager

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

async def _run_graph_build(app, task_id: str):
    """Background task wrapper."""
    try:
        task_manager.update_progress(task_id, 0.0, phase="starting", message="Starting build")
        
        # Run synchronous blocking builder in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, app.state.graph_builder.build_graph_from_db, task_id)
        
    except Exception as e:
        logger.exception("Graph build failed")
        task_manager.mark_failed(task_id, str(e))

@router.post("/build")
async def build_graph(request: Request, background_tasks: BackgroundTasks):
    """Start graph build process."""
    task_id = task_manager.create_task(task_type="graph_build")
    
    # Launch background task
    background_tasks.add_task(_run_graph_build, request.app, task_id)
    
    return {"task_id": task_id, "status": "started"}

@router.get("/status/{task_id}")
async def get_graph_status(task_id: str):
    """Get graph build status."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
