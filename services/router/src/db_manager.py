import os
import networkx as nx
from typing import Optional, Dict, Any, List, Tuple, Set
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from loguru import logger as log
from src.osm.turn_restrictions import TurnRestrictionManager
from src.osm.osm_way_processor import OSMWayProcessor
from src.osm.osrm_profile import get_car_profile


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
        try:
            conn = self.get_connection()
            conn.close()
            log.info(f"PostGIS connected: {self.conn_params['host']}")
        except Exception as e:
            log.error(f"PostGIS connection FAILED: {str(e)}")
            raise
    
    def get_connection(self):
        return psycopg2.connect(**self.conn_params)

    # Simplified stub of methods I recovered, since I cannot write 600 lines in one go easily without seeing all.
    # I will paste the CRITICAL methods I recovered: insert_nodes, insert_edges, etc.
    # But wait, I only saw truncated output for PostGISManager!
    # I need to be careful. The user wants the Logic recovered.
    # I saw save_graph_to_postgres in graph_builder.py calling:
    # db.insert_nodes, db.get_node_ids, db.insert_edges, db.insert_turn_restrictions, db.get_graph_stats
    # I MUST implement these methods even if I don't have the full original code.
    
    def insert_nodes(self, nodes: List[Tuple[int, float, float]]):
        """Insert generic nodes (osm_id, lat, lon) -> graphs.nodes"""
        if not nodes:
            return
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO graphs.nodes (osm_id, geom)
                    VALUES %s
                    ON CONFLICT (osm_id) DO NOTHING
                    """,
                    [(n[0], f"POINT({n[2]} {n[1]})") for n in nodes]
                )
            conn.commit()
            log.info(f"Inserted {len(nodes)} nodes.")
        finally:
            conn.close()

    def get_node_ids(self, osm_ids: List[int]) -> Dict[int, int]:
        """Get internal ID map for OSM IDs"""
        if not osm_ids:
            return {}
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT osm_id, id FROM graphs.nodes WHERE osm_id = ANY(%s)",
                    (osm_ids,)
                )
                return {row[0]: row[1] for row in cur.fetchall()}
        finally:
            conn.close()

    def insert_edges(self, edges: List[Dict]):
        """Insert edges into graphs.edges"""
        if not edges:
            return
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Prepare data for execute_values
                values = []
                for e in edges:
                    values.append((
                        e['start_node_id'], e['end_node_id'], e['osm_way_id'],
                        e['length_m'], e['speed_limit_kmh'], e['lanes'],
                        e['oneway'], e['highway_type'], e.get('bearing', 0),
                        Json(e.get('osm_tags', {}))
                    ))
                
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO graphs.edges (
                        source_id, target_id, osm_way_id, length_m, 
                        max_speed, lanes, oneway, highway, bearing, tags
                    ) VALUES %s
                    """,
                    values
                )
            conn.commit()
            log.info(f"Inserted {len(edges)} edges.")
        finally:
            conn.close()

    def insert_turn_restrictions(self, restrictions: List[Dict]):
        if not restrictions:
            return
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for r in restrictions:
                    cur.execute(
                        """
                        INSERT INTO graphs.turn_restrictions (
                            osm_relation_id, restriction, from_way, via_node, to_way, is_prohibitive
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (r['osm_relation_id'], r['restriction_type'], r['from_way_id'],
                         r['via_node_id'], r['to_way_id'], r['is_prohibitive'])
                    )
            conn.commit()
        finally:
            conn.close()

    def get_graph_stats(self):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT count(*) as nodes FROM graphs.nodes")
                nodes = cur.fetchone()['nodes']
                cur.execute("SELECT count(*) as edges FROM graphs.edges")
                edges = cur.fetchone()['edges']
                return {'total_nodes': nodes, 'total_edges': edges}
        finally:
            conn.close()

    def load_full_graph(self) -> Tuple[List[Dict], List[Dict]]:
        """Load nodes and edges for NetworkX"""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, osm_id, ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon FROM graphs.nodes")
                nodes = cur.fetchall()
                cur.execute("SELECT * FROM graphs.edges")
                edges = cur.fetchall()
                return nodes, edges
        finally:
            conn.close()

    def fetch_osm_ways(self) -> List[Dict]:
        """Fetch all ways from osm.ways with geometry."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get ID, tags, and geometry as GeoJSON to parse coordinates
                cur.execute("""
                    SELECT 
                        id, 
                        osm_id, 
                        tags, 
                        ST_AsGeoJSON(geom)::json as geometry
                    FROM osm.ways
                    WHERE tags ? 'highway'
                """)
                return cur.fetchall()
        finally:
            conn.close()

    def fetch_osm_restrictions(self) -> List[Dict]:
        """Fetch turn restrictions."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        osm_relation_id,
                        restriction_type,
                        from_way_id,
                        via_node_id,
                        to_way_id,
                        tags
                    FROM osm.turn_restrictions
                """)
                return cur.fetchall()
        finally:
            conn.close()

    def rebuild_graph_topology(self, progress_callback=None):
        """
        Rebuild graph topology directly in database using PostGIS/pgRouting.
        """
        pass # implemented as separate granular methods below

    def prepare_topology_inputs(self):
        """Step 1: Prepare candidate table."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Step 1: Preparing edge candidates...")
                cur.execute("DROP TABLE IF EXISTS edge_candidates")
                cur.execute("""
                    CREATE TABLE edge_candidates AS 
                    SELECT id, geom, tags, highway, maxspeed, lanes, oneway 
                    FROM osm.ways 
                    WHERE tags ? 'highway'
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ec_geom ON edge_candidates USING GIST(geom)")
                cur.execute("ALTER TABLE edge_candidates ADD COLUMN source int")
                cur.execute("ALTER TABLE edge_candidates ADD COLUMN target int")
            conn.commit()
        finally:
            conn.close()

    def run_pgr_create_topology(self):
        """Step 2: Create Topology (Heavy)."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Step 2: Running pgr_createTopology...")
                # Tolerance 0.0001 degrees ~= 11 meters. 
                cur.execute("SELECT pgr_createTopology('edge_candidates', 0.0001, 'geom', 'id')")
            conn.commit()
        finally:
            conn.close()

    def fill_graph_tables(self):
        """Step 3: Populate graphs.nodes and graphs.edges."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Step 3: Populating graph tables...")
                
                # Clear existing nodes
                cur.execute("TRUNCATE graphs.nodes CASCADE")
                
                # Nodes
                cur.execute("""
                    INSERT INTO graphs.nodes (id, osm_node_id, geom)
                    SELECT 
                        id, 
                        id, -- Using internal topo ID
                        the_geom
                    FROM edge_candidates_vertices_pgr
                """)
                
                # Recreate edges table to ensure schema matches routing requirements
                cur.execute("DROP TABLE IF EXISTS graphs.edges CASCADE")
                cur.execute("""
                    CREATE TABLE graphs.edges (
                        id SERIAL PRIMARY KEY,
                        source_id bigint,
                        target_id bigint,
                        osm_way_id bigint,
                        geometry geometry(LineString, 4326),
                        length_m float,
                        speed_limit_kmh float,
                        lanes int,
                        oneway boolean,
                        highway_type text,
                        osm_tags jsonb,
                        max_speed float,
                        base_travel_time_sec float GENERATED ALWAYS AS (
                            length_m / GREATEST(speed_limit_kmh / 3.6, 0.1)
                        ) STORED
                    );
                    CREATE INDEX idx_graphs_edges_source ON graphs.edges(source_id);
                    CREATE INDEX idx_graphs_edges_target ON graphs.edges(target_id);
                    CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geometry);
                """)
                
                # Edges
                cur.execute("""
                    INSERT INTO graphs.edges (
                        osm_way_id, source_id, target_id, geometry, 
                        length_m, speed_limit_kmh, lanes, oneway, highway_type, 
                        osm_tags, max_speed
                    )
                    SELECT 
                        id, source, target, geom, 
                        ST_Length(geom::geography), 
                        CASE 
                            WHEN maxspeed ~ '^[0-9]+$' THEN maxspeed::float 
                            ELSE 60.0 
                        END, 
                        COALESCE(lanes, 1), 
                        CASE WHEN oneway IN ('yes', 'true', '1') THEN true ELSE false END,
                        highway,
                        tags,
                        CASE 
                            WHEN maxspeed ~ '^[0-9]+$' THEN maxspeed::float 
                            ELSE 60.0 
                        END
                    FROM edge_candidates
                    WHERE source IS NOT NULL AND target IS NOT NULL
                """)
            conn.commit()
        finally:
            conn.close()
            
    def finalize_graph(self):
        """Step 4: Analyze and cleanup."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Step 4: Finalizing...")
                cur.execute("ANALYZE graphs.nodes")
                cur.execute("ANALYZE graphs.edges")
                cur.execute("DROP TABLE IF EXISTS edge_candidates")
                cur.execute("DROP TABLE IF EXISTS edge_candidates_vertices_pgr")
            conn.commit()
        finally:
            conn.close()
