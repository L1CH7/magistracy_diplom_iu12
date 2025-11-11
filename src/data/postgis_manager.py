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
            log.info(
                f"PostGIS connected: host={self.conn_params['host']}, "
                f"db={self.conn_params['database']}"
            )
        except Exception as e:
            log.error(f"PostGIS connection FAILED: {str(e)}")
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
                    "SELECT tiles.get_tile(%s::smallint, %s, %s, %s::varchar)",
                    (z, x, y, source)
                )
                result = cur.fetchone()
                if result and result[0]:
                    log.debug(
                        f"Tile cache HIT: z={z} x={x} y={y} "
                        f"source={source}"
                    )
                    return bytes(result[0])
                else:
                    log.debug(
                        f"Tile cache MISS: z={z} x={x} y={y} "
                        f"source={source}"
                    )
                return None
        except Exception as e:
            log.error(f"Tile get FAILED: z={z} x={x} y={y} error={str(e)}")
            raise
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
                    "SELECT tiles.insert_tile("
                    "%s::smallint, %s, %s, %s, %s::varchar)",
                    (z, x, y, psycopg2.Binary(tile_data), source)
                )
            conn.commit()
            log.info(
                f"Tile CACHED: z={z} x={x} y={y} size={len(tile_data)} "
                f"source={source}"
            )
        except Exception as e:
            conn.rollback()
            log.error(
                f"Tile cache FAILED: z={z} x={x} y={y} error={str(e)}"
            )
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
                    geojson = result[0]
                    feature_count = len(geojson.get('features', []))
                    log.info(
                        f"OSM GeoJSON fetched from cache: "
                        f"bbox={bbox} features={feature_count}"
                    )
                    return geojson
                else:
                    log.debug(f"OSM cache MISS for bbox={bbox}")
                return None
        except Exception as e:
            log.error(f"OSM GeoJSON fetch FAILED: bbox={bbox} error={str(e)}")
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
            log.info(
                f"OSM ways INSERTED: count={len(ways_data)} region={region}"
            )
        except Exception as e:
            conn.rollback()
            log.error(f"OSM bulk insert FAILED: error={str(e)}")
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
            log.info(f"Region CREATED: name={region_name} id={region_id}")
            return region_id
        except Exception as e:
            conn.rollback()
            log.error(
                f"Region create FAILED: name={region_name} error={str(e)}"
            )
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
            log.info(
                f"Region marked COMPLETE: name={region_name} "
                f"ways={total_ways} elements={total_elements}"
            )
        except Exception as e:
            conn.rollback()
            log.error(
                f"Region mark FAILED: name={region_name} error={str(e)}"
            )
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
    # GRAPHS SCHEMA - processed GeoJSON cache
    # ========================================================================
    
    def get_processed_geojson(
        self,
        bbox: Tuple[float, float, float, float],
        style_version: str = 'v1'
    ) -> Optional[Dict[str, Any]]:
        """Get cached processed (filtered + classified) GeoJSON.
        
        This cache stores GeoJSON after:
        - Filtering to drivable roads
        - Adding classification metadata (colors, widths, etc.)
        - Coordinate rounding
        
        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            style_version: Style version identifier (for cache invalidation)
            
        Returns:
            Processed GeoJSON FeatureCollection or None if cache miss
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                cur.execute(
                    """
                    SELECT data FROM graphs.processed_geojson
                    WHERE min_lon = %s AND min_lat = %s
                      AND max_lon = %s AND max_lat = %s
                      AND style_version = %s
                    """,
                    (min_lon, min_lat, max_lon, max_lat, style_version)
                )
                result = cur.fetchone()
                if result and result[0]:
                    geojson = result[0]
                    feature_count = len(geojson.get('features', []))
                    log.info(
                        f"Processed GeoJSON cache HIT: "
                        f"bbox={bbox} features={feature_count}"
                    )
                    return geojson
                else:
                    log.debug(
                        f"Processed GeoJSON cache MISS: bbox={bbox}"
                    )
                return None
        except Exception as e:
            log.error(
                f"Processed GeoJSON fetch FAILED: "
                f"bbox={bbox} error={str(e)}"
            )
            return None
        finally:
            conn.close()
    
    def save_processed_geojson(
        self,
        bbox: Tuple[float, float, float, float],
        geojson: Dict[str, Any],
        style_version: str = 'v1'
    ):
        """Save processed GeoJSON to cache.
        
        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            geojson: Processed GeoJSON FeatureCollection
            style_version: Style version identifier
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                feature_count = len(geojson.get('features', []))
                
                cur.execute(
                    """
                    INSERT INTO graphs.processed_geojson 
                        (min_lon, min_lat, max_lon, max_lat, 
                         style_version, data, feature_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (min_lon, min_lat, max_lon, max_lat, style_version)
                    DO UPDATE SET
                        data = EXCLUDED.data,
                        feature_count = EXCLUDED.feature_count,
                        updated_at = NOW()
                    """,
                    (min_lon, min_lat, max_lon, max_lat, 
                     style_version, Json(geojson), feature_count)
                )
            conn.commit()
            log.info(
                f"Processed GeoJSON SAVED: "
                f"bbox={bbox} features={feature_count}"
            )
        except Exception as e:
            conn.rollback()
            log.error(
                f"Processed GeoJSON save FAILED: "
                f"bbox={bbox} error={str(e)}"
            )
            raise
        finally:
            conn.close()
    
    # ========================================================================
    # GRAPH OPERATIONS - nodes and edges tables
    # ========================================================================
    
    def insert_nodes(self, nodes: List[Tuple[int, float, float]]):
        """Bulk insert nodes into graph.
        
        Args:
            nodes: List of (osm_node_id, lat, lon) tuples
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Use ON CONFLICT DO NOTHING для idempotency
                node_data = [
                    (osm_id, lat, lon, lon, lat)
                    for osm_id, lat, lon in nodes
                ]
                cur.executemany(
                    """
                    INSERT INTO nodes (osm_node_id, lat, lon, geometry)
                    VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    ON CONFLICT (osm_node_id) DO NOTHING
                    """,
                    node_data
                )
            conn.commit()
            log.info(f"Nodes INSERTED: count={len(nodes)}")
        except Exception as e:
            conn.rollback()
            log.error(f"Nodes insert FAILED: error={str(e)}")
            raise
        finally:
            conn.close()
    
    def insert_edges(self, edges: List[Dict[str, Any]]):
        """Bulk insert edges into graph.
        
        Args:
            edges: List of edge dicts with keys:
                osm_way_id, start_node_id, end_node_id,
                geometry_coords (list of [lon, lat]),
                length_m, speed_limit_kmh, lanes, oneway, highway_type,
                osm_tags (optional dict)
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for edge in edges:
                    # Build LineString from coordinates
                    coords = edge['geometry_coords']
                    linestring = 'LINESTRING(' + ','.join(
                        f"{lon} {lat}" for lon, lat in coords
                    ) + ')'
                    
                    cur.execute(
                        """
                        INSERT INTO edges (
                            osm_way_id, start_node_id, end_node_id,
                            geometry, length_m, speed_limit_kmh, lanes,
                            oneway, highway_type, osm_tags
                        )
                        VALUES (
                            %s, %s, %s,
                            ST_GeomFromText(%s, 4326),
                            %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (osm_way_id, start_node_id, end_node_id)
                        DO UPDATE SET
                            osm_tags = EXCLUDED.osm_tags,
                            last_updated = NOW()
                        """,
                        (
                            edge['osm_way_id'],
                            edge['start_node_id'],
                            edge['end_node_id'],
                            linestring,
                            edge['length_m'],
                            edge['speed_limit_kmh'],
                            edge['lanes'],
                            edge['oneway'],
                            edge['highway_type'],
                            Json(edge.get('osm_tags', {}))
                        )
                    )
            conn.commit()
            log.info(f"Edges INSERTED: count={len(edges)}")
        except Exception as e:
            conn.rollback()
            log.error(f"Edges insert FAILED: error={str(e)}")
            raise
        finally:
            conn.close()
    
    def get_node_ids(
        self,
        osm_node_ids: List[int]
    ) -> Dict[int, int]:
        """Map OSM node IDs to internal database IDs.
        
        Args:
            osm_node_ids: List of OSM node IDs
            
        Returns:
            Dict mapping osm_node_id → node.id
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT osm_node_id, id
                    FROM nodes
                    WHERE osm_node_id = ANY(%s)
                    """,
                    (osm_node_ids,)
                )
                return dict(cur.fetchall())
        finally:
            conn.close()
    
    def load_full_graph(self) -> Tuple[List[Dict], List[Dict]]:
        """Load entire graph from database.
        
        Returns:
            (nodes, edges) where each is a list of dicts
        """
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Load nodes
                cur.execute(
                    """
                    SELECT id, osm_node_id, lat, lon
                    FROM nodes
                    ORDER BY id
                    """
                )
                nodes = [dict(row) for row in cur.fetchall()]
                # Load edges with all attributes
                cur.execute(
                    """
                    SELECT
                        id, osm_way_id, start_node_id, end_node_id,
                        length_m, speed_limit_kmh, lanes, oneway,
                        highway_type, capacity, base_travel_time_sec,
                        bearing, current_load, effective_speed_kmh
                    FROM edges
                    ORDER BY id
                    """
                )
                edges = [dict(row) for row in cur.fetchall()]
                
                log.info(
                    f"Full graph LOADED: nodes={len(nodes)} edges={len(edges)}"
                )
                return nodes, edges
        finally:
            conn.close()
    
    def load_graph_by_bbox(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> Tuple[List[Dict], List[Dict]]:
        """Load graph subset intersecting with bbox.
        
        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            
        Returns:
            (nodes, edges) for visualization
        """
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                min_lon, min_lat, max_lon, max_lat = bbox
                # Find edges intersecting bbox
                cur.execute(
                    """
                    SELECT
                        id, osm_way_id, start_node_id, end_node_id,
                        length_m, speed_limit_kmh, lanes, oneway,
                        highway_type, capacity, base_travel_time_sec,
                        current_load, effective_speed_kmh
                    FROM edges
                    WHERE ST_Intersects(
                        geometry,
                        ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                    )
                    """,
                    (min_lon, min_lat, max_lon, max_lat)
                )
                edges = [dict(row) for row in cur.fetchall()]
                
                # Get unique node IDs from edges
                node_ids = set()
                for edge in edges:
                    node_ids.add(edge['start_node_id'])
                    node_ids.add(edge['end_node_id'])
                
                # Load nodes
                if node_ids:
                    cur.execute(
                        """
                        SELECT id, osm_node_id, lat, lon
                        FROM nodes
                        WHERE id = ANY(%s)
                        """,
                        (list(node_ids),)
                    )
                    nodes = [dict(row) for row in cur.fetchall()]
                else:
                    nodes = []
                
                log.info(
                    f"Graph by bbox LOADED: bbox={bbox} "
                    f"nodes={len(nodes)} edges={len(edges)}"
                )
                return nodes, edges
        finally:
            conn.close()
    
    def update_edge_load(
        self,
        edge_id: int,
        current_load: int,
        effective_speed_kmh: float
    ):
        """Update dynamic edge attributes during simulation.
        
        Args:
            edge_id: Edge database ID
            current_load: Current number of agents on edge
            effective_speed_kmh: Current effective speed
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE edges
                    SET current_load = %s,
                        effective_speed_kmh = %s,
                        last_updated = NOW()
                    WHERE id = %s
                    """,
                    (current_load, effective_speed_kmh, edge_id)
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error(
                f"Edge load update FAILED: edge_id={edge_id} "
                f"error={str(e)}"
            )
            raise
        finally:
            conn.close()
    
    def batch_update_edge_loads(
        self,
        updates: List[Tuple[int, int, float]]
    ):
        """Batch update edge loads.
        
        Args:
            updates: List of (edge_id, current_load, effective_speed_kmh)
        """
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE edges
                    SET current_load = %s,
                        effective_speed_kmh = %s,
                        last_updated = NOW()
                    WHERE id = %s
                    """,
                    [(load, speed, eid) for eid, load, speed in updates]
                )
            conn.commit()
            log.debug(f"Edge loads UPDATED: count={len(updates)}")
        except Exception as e:
            conn.rollback()
            log.error(f"Batch edge load update FAILED: error={str(e)}")
            raise
        finally:
            conn.close()
    
    def get_graph_stats(self) -> Dict[str, Any]:
        """Get graph statistics using PostgreSQL function.
        
        Returns:
            Dict with total_nodes, total_edges, total_length_km, etc.
        """
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM get_graph_stats()")
                result = cur.fetchone()
                return dict(result) if result else {}
        finally:
            conn.close()
    
    # ========================================================================
    # TURN RESTRICTIONS
    # ========================================================================
    
    def insert_turn_restrictions(
        self,
        restrictions: List[Dict[str, Any]]
    ):
        """Bulk insert turn restrictions.
        
        Args:
            restrictions: List of dicts with keys:
                osm_relation_id, restriction_type, from_way_id,
                via_node_id, to_way_id, is_prohibitive, is_mandatory
        """
        if not restrictions:
            log.info("No turn restrictions to insert")
            return
        
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for r in restrictions:
                    cur.execute(
                        """
                        INSERT INTO turn_restrictions (
                            osm_relation_id, restriction_type,
                            from_way_id, via_node_id, to_way_id,
                            is_prohibitive, is_mandatory
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (osm_relation_id) DO NOTHING
                        """,
                        (
                            r['osm_relation_id'],
                            r['restriction_type'],
                            r['from_way_id'],
                            r['via_node_id'],
                            r['to_way_id'],
                            r['is_prohibitive'],
                            r['is_mandatory']
                        )
                    )
            conn.commit()
            log.info(
                "turn_restrictions_inserted",
                count=len(restrictions)
            )
        except Exception as e:
            conn.rollback()
            log.error(
                "turn_restrictions_insert_failed",
                error=str(e)
            )
            raise
        finally:
            conn.close()
    
    def load_turn_restrictions(self) -> List[Dict[str, Any]]:
        """Load all turn restrictions from database.
        
        Returns:
            List of restriction dicts
        """
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        osm_relation_id, restriction_type,
                        from_way_id, via_node_id, to_way_id,
                        is_prohibitive, is_mandatory
                    FROM turn_restrictions
                    ORDER BY via_node_id
                    """
                )
                results = cur.fetchall()
                return [dict(row) for row in results]
        finally:
            conn.close()
    
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
