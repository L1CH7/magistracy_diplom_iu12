"""Graph database manager - caching and retrieval of road graphs."""

import json
import gzip
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker, Session
from src.data.graph_db import Base, RoadGraphRegion, OSMElement
from src.utils.logging_config import get_logger

log = get_logger(__name__)


class GraphDBManager:
    """Manager for road graph database operations."""
    
    def __init__(self, db_url: str = "sqlite:///data/road_graphs.db"):
        """Initialize database connection."""
        self.engine = create_engine(db_url, echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        log.info("graph_db_initialized", db_url=db_url)
    
    def get_session(self) -> Session:
        """Get new database session."""
        return self.SessionLocal()
    
    def save_region_graph(
        self,
        region_name: str,
        bbox: Tuple[float, float, float, float],
        geojson: Dict[str, Any],
        total_ways: int,
        total_elements: int
    ) -> int:
        """Save road graph for a region.
        
        Args:
            region_name: Unique region identifier (e.g., 'moscow_oblast')
            bbox: (min_lat, min_lon, max_lat, max_lon)
            geojson: GeoJSON FeatureCollection
            total_ways: Number of way features
            total_elements: Total OSM elements processed
            
        Returns:
            Region ID
        """
        session = self.get_session()
        try:
            min_lat, min_lon, max_lat, max_lon = bbox
            
            # Compress GeoJSON
            geojson_str = json.dumps(geojson)
            compressed = gzip.compress(geojson_str.encode('utf-8'))
            
            log.info(
                "graph_compressing",
                region=region_name,
                original_size=len(geojson_str),
                compressed_size=len(compressed),
                ratio=f"{len(compressed) / len(geojson_str) * 100:.1f}%"
            )
            
            # Check if region exists
            existing = session.query(RoadGraphRegion).filter_by(
                region_name=region_name
            ).first()
            
            if existing:
                # Update existing
                existing.bbox_min_lat = min_lat
                existing.bbox_min_lon = min_lon
                existing.bbox_max_lat = max_lat
                existing.bbox_max_lon = max_lon
                existing.geojson_data = compressed.hex()
                existing.total_ways = total_ways
                existing.total_elements = total_elements
                existing.updated_at = datetime.utcnow()
                existing.is_complete = True
                region_id = existing.id
                log.info("graph_region_updated", region=region_name, id=region_id)
            else:
                # Create new
                region = RoadGraphRegion(
                    region_name=region_name,
                    bbox_min_lat=min_lat,
                    bbox_min_lon=min_lon,
                    bbox_max_lat=max_lat,
                    bbox_max_lon=max_lon,
                    geojson_data=compressed.hex(),
                    total_ways=total_ways,
                    total_elements=total_elements,
                    is_complete=True
                )
                session.add(region)
                session.flush()
                region_id = region.id
                log.info("graph_region_created", region=region_name, id=region_id)
            
            session.commit()
            return region_id
            
        except Exception as e:
            session.rollback()
            log.error("graph_save_failed", region=region_name, error=str(e))
            raise
        finally:
            session.close()
    
    def get_region_graph(self, region_name: str) -> Optional[Dict[str, Any]]:
        """Get cached road graph for a region.
        
        Returns:
            GeoJSON dict or None if not found
        """
        session = self.get_session()
        try:
            region = session.query(RoadGraphRegion).filter_by(
                region_name=region_name,
                is_complete=True
            ).first()
            
            if not region:
                log.info("graph_region_not_found", region=region_name)
                return None
            
            # Decompress
            compressed = bytes.fromhex(region.geojson_data)
            geojson_str = gzip.decompress(compressed).decode('utf-8')
            geojson = json.loads(geojson_str)
            
            log.info(
                "graph_region_loaded",
                region=region_name,
                ways=region.total_ways,
                age_hours=(datetime.utcnow() - region.updated_at).total_seconds() / 3600
            )
            
            return geojson
            
        except Exception as e:
            log.error("graph_load_failed", region=region_name, error=str(e))
            return None
        finally:
            session.close()
    
    def get_region_by_bbox(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[Dict[str, Any]]:
        """Find cached region that contains given bbox.
        
        Args:
            bbox: (min_lat, min_lon, max_lat, max_lon)
            
        Returns:
            GeoJSON dict or None
        """
        session = self.get_session()
        try:
            min_lat, min_lon, max_lat, max_lon = bbox
            
            # Find region that fully contains this bbox
            region = session.query(RoadGraphRegion).filter(
                and_(
                    RoadGraphRegion.bbox_min_lat <= min_lat,
                    RoadGraphRegion.bbox_min_lon <= min_lon,
                    RoadGraphRegion.bbox_max_lat >= max_lat,
                    RoadGraphRegion.bbox_max_lon >= max_lon,
                    RoadGraphRegion.is_complete == True  # noqa: E712
                )
            ).first()
            
            if not region:
                log.info("graph_no_cached_region_for_bbox", bbox=bbox)
                return None
            
            log.info("graph_found_cached_region", region=region.region_name, bbox=bbox)
            return self.get_region_graph(region.region_name)
            
        except Exception as e:
            log.error("graph_bbox_search_failed", bbox=bbox, error=str(e))
            return None
        finally:
            session.close()
    
    def list_regions(self) -> List[Dict[str, Any]]:
        """List all cached regions."""
        session = self.get_session()
        try:
            regions = session.query(RoadGraphRegion).all()
            return [
                {
                    "id": r.id,
                    "name": r.region_name,
                    "bbox": [r.bbox_min_lat, r.bbox_min_lon, r.bbox_max_lat, r.bbox_max_lon],
                    "total_ways": r.total_ways,
                    "total_elements": r.total_elements,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                    "is_complete": r.is_complete,
                }
                for r in regions
            ]
        finally:
            session.close()
