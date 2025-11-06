"""PostGIS database manager for tiles, OSM data, and graphs.

Manages three separate schemas:
- tiles: raster map tile caching
- osm: raw OSM data cache
- graphs: processed routing graphs and cached routes
"""

import os
from typing import Optional, Dict, Any, List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from src.utils.logger import setup_logger

log = setup_logger(__name__)


class PostGISManager:
    """Manager for PostGIS multi-schema database operations."""
    
    def __init__(self):
        """Initialize from environment variables."""
        self.conn_params = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', 5432)),
            'database': os.getenv('POSTGRES_DB', 'road_graphs'),
            'user': os.getenv('POSTGRES_USER', 'diplom'),
            'password': os.getenv('POSTGRES_PASSWORD', 'diplom_pass'),
        }
        self._test_connection()
    
    def _test_connection(self):
        """Test database connection on init."""
        try:
            conn = self.get_connection()
            conn.close()
            print(
                f"postgis_connected host={self.conn_params['host']} "
                f"db={self.conn_params['database']}"
            )
        except Exception as e:
            print(f"postgis_connection_failed error={str(e)}")
            raise
    
    def get_connection(self):
        """Get new database connection."""
        return psycopg2.connect(**self.conn_params)
    
    # ========================================================================
    # TILES SCHEMA - raster tile caching
    # ========================================================================
    
    def get_tile(
        self,
        z: int,
        x: int,
        y: int,
        source: str = 'osm'
    ) -> Optional[bytes]:
        """Get tile from cache (updates access stats).
        
        Returns:
            Tile bytes or None if not cached
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tiles.get_tile(%s, %s, %s, %s)",
                    (z, x, y, source)
                )
                result = cur.fetchone()
                if result and result[0]:
                    print(
                        "tile_cache_hit",
                        z=z, x=x, y=y, source=source
                    )
                    return bytes(result[0])
                return None
        finally:
            conn.close()
    
    def insert_tile(
        self,
        z: int,
        x: int,
        y: int,
        tile_data: bytes,
        source: str = 'osm'
    ):
        """Insert tile into cache."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tiles.insert_tile(%s, %s, %s, %s, %s)",
                    (z, x, y, psycopg2.Binary(tile_data), source)
                )
            conn.commit()
            print("tile_cached", z=z, x=x, y=y, source=source)
        except Exception as e:
            conn.rollback()
            print("tile_cache_failed", z=z, x=x, y=y, error=str(e))
            raise
        finally:
            conn.close()
    
    # ========================================================================
    # OSM SCHEMA - raw OSM data
    # ========================================================================
    
    def is_region_cached(self, region_name: str) -> bool:
        """Check if region is fully cached."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT osm.is_region_cached(%s)",
                    (region_name,)
                )
                return cur.fetchone()[0]
        finally:
            conn.close()
    
    def get_roads_geojson(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Optional[Dict[str, Any]]:
        """Get GeoJSON for roads in bbox.
        
        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            GeoJSON FeatureCollection
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                cur.execute(
                    "SELECT osm.get_roads_geojson(%s, %s, %s, %s)",
                    (min_lon, min_lat, max_lon, max_lat)
                )
                result = cur.fetchone()
                if result and result[0]:
                    print("osm_geojson_fetched", bbox=bbox)
                    return result[0]
                return None
        except Exception as e:
            print("osm_geojson_failed", bbox=bbox, error=str(e))
            return None
        finally:
            conn.close()
    
    def bulk_insert_ways(
        self,
        ways_data: List[Tuple[int, List[List[float]], Dict[str, Any]]],
        region: str = 'world'
    ):
        """Bulk insert OSM ways.
        
        Args:
            ways_data: List of (osm_id, coordinates, tags) tuples
            region: Region name for grouping
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for osm_id, coords, tags in ways_data:
                    cur.execute(
                        "SELECT osm.insert_way(%s, %s, %s, %s)",
                        (osm_id, Json(coords), Json(tags), region)
                    )
            conn.commit()
            print(
                "osm_ways_inserted",
                count=len(ways_data),
                region=region
            )
        except Exception as e:
            conn.rollback()
            print("osm_bulk_insert_failed", error=str(e))
            raise
        finally:
            conn.close()
    
    def create_region(
        self,
        region_name: str,
        bbox: Tuple[float, float, float, float]
    ) -> int:
        """Create region metadata.
        
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
                # Create polygon from bbox
                cur.execute(
                    """
                    INSERT INTO osm.regions (name, bbox)
                    VALUES (%s, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                    ON CONFLICT (name)
                    DO UPDATE SET updated_at = NOW()
                    RETURNING id
                    """,
                    (region_name, min_lon, min_lat, max_lon, max_lat)
                )
                region_id = cur.fetchone()[0]
            conn.commit()
            print("region_created", name=region_name, id=region_id)
            return region_id
        except Exception as e:
            conn.rollback()
            print("region_create_failed", name=region_name, error=str(e))
            raise
        finally:
            conn.close()
    
    def mark_region_complete(
        self,
        region_name: str,
        total_ways: int,
        total_elements: int
    ):
        """Mark region as fully loaded."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE osm.regions
                    SET is_complete = TRUE,
                        total_ways = %s,
                        total_elements = %s,
                        updated_at = NOW()
                    WHERE name = %s
                    """,
                    (total_ways, total_elements, region_name)
                )
            conn.commit()
            print(
                "region_marked_complete",
                name=region_name,
                ways=total_ways,
                elements=total_elements
            )
        except Exception as e:
            conn.rollback()
            print("region_mark_failed", name=region_name, error=str(e))
            raise
        finally:
            conn.close()
    
    def list_regions(self) -> List[Dict[str, Any]]:
        """List all cached regions."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT name, total_ways, total_elements,
                           is_complete, created_at, updated_at
                    FROM osm.regions
                    ORDER BY created_at DESC
                    """
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    
    # ========================================================================
    # GRAPHS SCHEMA - routing graphs (future use)
    # ========================================================================
    
    # Reserved for future graph operations
    # def build_graph_from_region(self, region_name: str): ...
    # def cache_route(self, from_id, to_id, edges): ...
    # def get_cached_route(self, from_id, to_id): ...
    
    # ========================================================================
    # STATISTICS
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics for all schemas."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT public.get_db_stats()")
                result = cur.fetchone()
                if result and result[0]:
                    return result[0]
                return {}
        finally:
            conn.close()
