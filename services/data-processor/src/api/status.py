"""
Status API - real-time system status endpoints.

Endpoints:
- GET /api/v1/status - global system status
- GET /api/v1/tasks - all active tasks
- GET /api/v1/tasks/{task_id} - specific task details
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

from ..state.task_manager import TaskManager
from ..db.pool import DatabasePool
from ..db.queries import OSMQueries


router = APIRouter(prefix="/api/v1", tags=["status"])


async def init_status_api(db: DatabasePool, task_manager: TaskManager):
    """Initialize status API with dependencies."""
    router.db = db
    router.task_manager = task_manager


@router.get("/status")
async def get_system_status():
    """
    Get real-time system status.
    
    Returns:
        {
            "tasks": {...},
            "database": {...}
        }
    """
    try:
        # Task statistics
        task_stats = router.task_manager.get_stats()
        all_tasks = router.task_manager.get_all_tasks()
        
        # Database statistics
        async with router.db.acquire() as conn:
            ways_count = await conn.fetchval(OSMQueries.GET_WAYS_COUNT)
            cached_tiles = await conn.fetchval(
                OSMQueries.GET_CACHED_TILES_COUNT
            )
            downloading_tiles = await conn.fetchval(
                OSMQueries.GET_DOWNLOADING_TILES_COUNT
            )
            failed_tiles = await conn.fetchval(
                OSMQueries.GET_FAILED_TILES_COUNT
            )
        
        return {
            "tasks": {
                "statistics": task_stats,
                "by_phase": {
                    "downloading": len(all_tasks["downloading"]),
                    "saving": len(all_tasks["saving"]),
                    "building_graph": len(all_tasks["building_graph"]),
                    "complete": len(all_tasks["complete"]),
                    "failed": len(all_tasks["failed"])
                }
            },
            "database": {
                "ways": ways_count,
                "tiles_cached": cached_tiles,
                "tiles_downloading": downloading_tiles,
                "tiles_failed": failed_tiles
            }
        }
        
    except Exception as e:
        logger.error(f"Status endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def get_all_tasks():
    """
    Get all tasks grouped by phase.
    
    Returns:
        {
            "downloading": [...],
            "saving": [...],
            "complete": [...],
            "failed": [...]
        }
    """
    return router.task_manager.get_all_tasks()


@router.get("/tasks/{task_id}")
async def get_task_details(task_id: str):
    """
    Get details of specific task.
    
    Args:
        task_id: Task identifier
    
    Returns:
        Task state dict
    """
    task = router.task_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task
