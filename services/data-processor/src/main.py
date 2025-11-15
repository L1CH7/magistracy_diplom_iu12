"""
Data Processor Service - OSM data fetching and graph construction.

Responsibilities:
- Fetch OSM data (Overpass API)
- Build road graph (nodes, edges)
- Calculate bearings (azimuth)
- Calculate capacity (by speed_limit and mode)
- Pre-compute geom_3857 for MVT tiles
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from loguru import logger


from .manager import DataProcessorManager  # noqa: E402
from .models import (  # noqa: E402
    FetchDataRequest,
    FetchDataResponse,
    ProcessGraphRequest,
    ProcessGraphResponse
)


# Global manager
data_manager: DataProcessorManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global data_manager
    
    logger.info("Starting Data Processor Service...")
    
    # Initialize manager
    data_manager = DataProcessorManager()
    await data_manager.initialize()
    
    logger.success("Data Processor Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Data Processor Service...")
    await data_manager.shutdown()
    logger.success("Data Processor Service stopped")


app = FastAPI(
    title="Data Processor Service",
    description="OSM data fetching and graph construction",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "data-processor"
    }


@app.post("/api/v1/data/fetch", response_model=FetchDataResponse)
async def fetch_osm_data(
    request: FetchDataRequest,
    background_tasks: BackgroundTasks
):
    """
    Fetch OSM data for bounding box.
    
    Uses Overpass API.
    Returns job_id, runs in background.
    """
    job_id = await data_manager.start_fetch_job(
        bbox=request.bbox,
        highway_types=request.highway_types
    )
    
    # Run in background
    background_tasks.add_task(
        data_manager.run_fetch_job,
        job_id
    )
    
    return FetchDataResponse(
        job_id=job_id,
        status="started"
    )


@app.get("/api/v1/data/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get fetch job status."""
    status = await data_manager.get_job_status(job_id)
    
    return status


@app.post("/api/v1/graph/process", response_model=ProcessGraphResponse)
async def process_graph(
    request: ProcessGraphRequest,
    background_tasks: BackgroundTasks
):
    """
    Process raw OSM data into graph.
    
    Steps:
    1. Build nodes and edges
    2. Calculate bearings
    3. Calculate capacity
    4. Pre-compute geom_3857
    5. Create spatial indexes
    
    Returns job_id, runs in background.
    """
    job_id = await data_manager.start_process_job(
        osm_data_path=request.osm_data_path,
        capacity_mode=request.capacity_mode
    )
    
    # Run in background
    background_tasks.add_task(
        data_manager.run_process_job,
        job_id
    )
    
    return ProcessGraphResponse(
        job_id=job_id,
        status="started"
    )


@app.get("/api/v1/graph/jobs/{job_id}")
async def get_process_job_status(job_id: str):
    """Get graph processing job status."""
    status = await data_manager.get_job_status(job_id)
    
    return status
