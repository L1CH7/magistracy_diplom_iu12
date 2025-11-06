# Graph Database Schema

"""SQLAlchemy models for road graph caching."""

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class RoadGraphRegion(Base):
    """Cached road graph data for a specific region."""
    
    __tablename__ = 'road_graph_regions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Region identification
    region_name = Column(String(255), nullable=False, unique=True, index=True)
    bbox_min_lat = Column(Float, nullable=False)
    bbox_min_lon = Column(Float, nullable=False)
    bbox_max_lat = Column(Float, nullable=False)
    bbox_max_lon = Column(Float, nullable=False)
    
    # GeoJSON data (compressed)
    geojson_data = Column(Text, nullable=False)  # JSON string
    
    # Metadata
    total_ways = Column(Integer, nullable=False, default=0)
    total_elements = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Status
    is_complete = Column(Boolean, nullable=False, default=False)
    
    # Index for bbox queries
    __table_args__ = (
        Index('idx_bbox', 'bbox_min_lat', 'bbox_min_lon', 'bbox_max_lat', 'bbox_max_lon'),
    )
    
    def __repr__(self):
        return f"<RoadGraphRegion(region='{self.region_name}', ways={self.total_ways})>"


class OSMElement(Base):
    """Individual OSM elements (nodes/ways) for detailed queries."""
    
    __tablename__ = 'osm_elements'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # OSM identification
    osm_type = Column(String(10), nullable=False, index=True)  # 'node' or 'way'
    osm_id = Column(Integer, nullable=False, index=True)
    
    # Location (for nodes)
    lat = Column(Float)
    lon = Column(Float)
    
    # Tags (JSON)
    tags = Column(Text)  # JSON string
    
    # Relations
    region_id = Column(Integer, index=True)  # FK to road_graph_regions.id
    
    # Index for OSM ID lookups
    __table_args__ = (
        Index('idx_osm_unique', 'osm_type', 'osm_id', unique=True),
        Index('idx_location', 'lat', 'lon'),
    )
    
    def __repr__(self):
        return f"<OSMElement(type='{self.osm_type}', osm_id={self.osm_id})>"
