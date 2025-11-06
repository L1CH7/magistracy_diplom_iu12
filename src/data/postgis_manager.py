"""PostGIS database connection and operations for road graphs."""

import os
import json
from typing import Optional, Dict, Any, List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from src.utils.logging_config import get_logger

log = get_logger(__name__)


class PostGISManager:
    """Manager for PostGIS database operations."""
    
    def __init__(self):
        """Initialize database connection from environment variables."""
        self.conn_params = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DB', 'road_graphs'),
            'user': os.getenv('POSTGRES_USER', 'diplom'),
            'password': os.getenv('POSTGRES_PASSWORD', 'diplom_pass'),
        }
        self._test_connection()
    
    def _test_connection(self):
        """Test database connection on initialization."""
        try:
            conn = self.get_connection()
            conn.close()
            log.info("postgis_connected", **self.conn_params)
        except Exception as e:
            log.error("postgis_connection_failed", error=str(e), **self.conn_params)
            raise
    
    def get_connection(self):
        """Get new database connection."""
        return psycopg2.connect(**self.conn_params)
    
    def is_region_cached(self, region_name: str) -> bool:
        """Check if region is fully cached in database."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_region_cached(%s)",
                    (region_name,)
                )
                return cur.fetchone()[0]
        finally:
            conn.close()
    
    def get_roads_geojson(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[Dict[str, Any]]:
        """Get GeoJSON for roads in bbox using PostGIS function.
        
        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            GeoJSON FeatureCollection or None
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                cur.execute(
                    "SELECT get_roads_geojson(%s, %s, %s, %s)",
                    (min_lon, min_lat, max_lon, max_lat)
                )
                result = cur.fetchone()
                if result and result[0]:
                    log.info("postgis_geojson_fetched", bbox=bbox)
                    return result[0]
                return None
        except Exception as e:
            log.error("postgis_geojson_failed", bbox=bbox, error=str(e))
            return None
        finally:
            conn.close()
    
    def insert_way(
        self,
        osm_id: int,
        coordinates: List[List[float]],
        tags: Dict[str, Any],
        region: str = 'unknown'
    ):
        """Insert OSM way into database.
        
        Args:
            osm_id: OSM way ID
            coordinates: [[lon, lat], [lon, lat], ...]
            tags: OSM tags dict
            region: Region name for grouping
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT insert_way(%s, %s, %s, %s)",
                    (osm_id, Json(coordinates), Json(tags), region)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("postgis_insert_way_failed", osm_id=osm_id, error=str(e))
            raise
        finally:
            conn.close()
    
    def bulk_insert_ways(
        self,
        ways_data: List[Tuple[int, List[List[float]], Dict[str, Any]]],
        region: str = 'unknown'
    ):
        """Bulk insert multiple ways efficiently.
        
        Args:
            ways_data: List of (osm_id, coordinates, tags) tuples
            region: Region name
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for osm_id, coords, tags in ways_data:
                    cur.execute(
                        "SELECT insert_way(%s, %s, %s, %s)",
                        (osm_id, Json(coords), Json(tags), region)
                    )
            conn.commit()
            log.info("postgis_bulk_insert_complete", count=len(ways_data), region=region)
        except Exception as e:
            conn.rollback()
            log.error("postgis_bulk_insert_failed", count=len(ways_data), error=str(e))
            raise
        finally:
            conn.close()
    
    def create_region(
        self,
        region_name: str,
        bbox: Tuple[float, float, float, float]
    ) -> int:
        """Create or update region metadata.
        
        Args:
            region_name: Unique region identifier
            bbox: (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            Region ID
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                
                # Create bbox polygon
                cur.execute(
                    """
                    INSERT INTO cached_regions (region_name, bbox, fetch_started_at)
                    VALUES (%s, ST_MakeEnvelope(%s, %s, %s, %s, 4326), NOW())
                    ON CONFLICT (region_name) DO UPDATE SET
                        bbox = EXCLUDED.bbox,
                        fetch_started_at = NOW(),
                        is_complete = FALSE
                    RETURNING id
                    """,
                    (region_name, min_lon, min_lat, max_lon, max_lat)
                )
                region_id = cur.fetchone()[0]
            conn.commit()
            log.info("postgis_region_created", region=region_name, id=region_id)
            return region_id
        except Exception as e:
            conn.rollback()
            log.error("postgis_region_create_failed", region=region_name, error=str(e))
            raise
        finally:
            conn.close()
    
    def mark_region_complete(
        self,
        region_name: str,
        total_ways: int,
        total_elements: int
    ):
        """Mark region as fully fetched and cached.
        
        Args:
            region_name: Region identifier
            total_ways: Number of ways stored
            total_elements: Total OSM elements processed
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cached_regions SET
                        is_complete = TRUE,
                        fetch_completed_at = NOW(),
                        total_ways = %s,
                        total_elements = %s,
                        updated_at = NOW()
                    WHERE region_name = %s
                    """,
                    (total_ways, total_elements, region_name)
                )
            conn.commit()
            log.info("postgis_region_marked_complete", region=region_name, ways=total_ways)
        except Exception as e:
            conn.rollback()
            log.error("postgis_mark_complete_failed", region=region_name, error=str(e))
            raise
        finally:
            conn.close()
    
    def list_regions(self) -> List[Dict[str, Any]]:
        """List all cached regions with metadata."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        id,
                        region_name,
                        ST_AsGeoJSON(bbox)::json as bbox,
                        total_ways,
                        total_elements,
                        is_complete,
                        created_at,
                        updated_at,
                        fetch_started_at,
                        fetch_completed_at
                    FROM cached_regions
                    ORDER BY updated_at DESC
                    """
                )
                return cur.fetchall()
        finally:
            conn.close()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        (SELECT COUNT(*) FROM osm_ways) as total_ways,
                        (SELECT COUNT(*) FROM osm_nodes) as total_nodes,
                        (SELECT COUNT(*) FROM cached_regions WHERE is_complete = TRUE) as complete_regions,
                        (SELECT pg_size_pretty(pg_total_relation_size('osm_ways'))) as ways_size,
                        (SELECT pg_size_pretty(pg_total_relation_size('osm_nodes'))) as nodes_size
                    """
                )
                return dict(cur.fetchone())
        finally:
            conn.close()
