"""
Data Processor models.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class FetchDataRequest(BaseModel):
    """Request to fetch OSM data."""
    
    bbox: List[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Bounding box [min_lat, min_lon, max_lat, max_lon]"
    )
    
    highway_types: List[str] = Field(
        default=[
            "motorway", "trunk", "primary", "secondary",
            "tertiary", "residential", "service"
        ],
        description="OSM highway types to fetch"
    )


class FetchDataResponse(BaseModel):
    """Response for fetch job."""
    
    job_id: str = Field(..., description="Job ID")
    status: str = Field(
        ...,
        description="Job status (started/running/done/error)"
    )


class ProcessGraphRequest(BaseModel):
    """Request to process OSM data into graph."""
    
    osm_data_path: str = Field(
        ...,
        description="Path to OSM JSON file"
    )
    
    capacity_mode: str = Field(
        default="simple",
        description="Capacity calculation mode (simple/realistic)"
    )


class ProcessGraphResponse(BaseModel):
    """Response for graph processing job."""
    
    job_id: str = Field(..., description="Job ID")
    status: str = Field(..., description="Job status")


class TileKey(BaseModel):
    """OSM tile key (0.5°x0.5°)."""
    
    lon: float = Field(..., description="Longitude (left edge)")
    lat: float = Field(..., description="Latitude (bottom edge)")


class TileStatusResponse(BaseModel):
    """Tile availability status."""
    
    tile: TileKey
    exists_in_db: bool = Field(..., description="Tile в БД")
    ways_count: Optional[int] = Field(
        None,
        description="Количество ways в тайле"
    )
    download_status: Optional[str] = Field(
        None,
        description="Статус скачивания (downloading/done/error)"
    )


class GlobalStatusResponse(BaseModel):
    """Global data processor status."""
    
    active_downloads: int = Field(
        ...,
        description="Количество активных скачиваний"
    )
    total_tiles_in_db: int = Field(
        ...,
        description="Всего тайлов в БД"
    )
    downloading_tiles: List[TileKey] = Field(
        default_factory=list,
        description="Список скачивающихся тайлов"
    )
