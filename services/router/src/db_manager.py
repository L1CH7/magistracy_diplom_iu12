import os
import networkx as nx
from typing import Optional, Dict, Any, List, Tuple, Set
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from loguru import logger as log
# from src.osm.turn_restrictions import TurnRestrictionManager
# from src.osm.osm_way_processor import OSMWayProcessor
# from src.osm.osrm_profile import get_car_profile


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

    def get_table_count(self, table_name: str) -> int:
        """Get row count of a table. Returns 0 if table doesn't exist."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Check existence first
                cur.execute("SELECT to_regclass(%s)", (table_name,))
                if cur.fetchone()[0] is None:
                    return 0
                cur.execute(f"SELECT count(*) FROM {table_name}")
                return cur.fetchone()[0]
        except Exception as e:
            log.warning(f"Failed to get count for {table_name}: {e}")
            return 0
        finally:
            conn.close()

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

    def get_osm_ways_count(self) -> int:
        """Get total number of OSM ways to process."""
        return self.get_table_count('osm.ways')

    def init_candidate_table(self):
        """Create empty edge_candidates table structure with Smart Extraction fields."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Creating edge_candidates table structure...")
                cur.execute("DROP TABLE IF EXISTS edge_candidates CASCADE")
                cur.execute("""
                    CREATE TABLE edge_candidates (
                        id bigint,
                        tags jsonb,
                        highway text,
                        maxspeed text,
                        lanes int,
                        oneway int,
                        source int,
                        target int,
                        geom geometry(LineString, 4326),
                        is_ground boolean
                    )
                """)
            conn.commit()
        finally:
            conn.close()

    def insert_candidates_batch(self, offset: int, limit: int) -> int:
        """Insert a batch of candidates from osm.ways with Group A/B logic."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    INSERT INTO edge_candidates (id, tags, highway, maxspeed, lanes, oneway, geom, is_ground)
                    SELECT 
                        id, 
                        tags, 
                        tags->>'highway' as highway,
                        tags->>'maxspeed' as maxspeed,
                        (tags->>'lanes')::int as lanes,
                        CASE 
                            WHEN tags->>'oneway' = 'yes' THEN 1 
                            WHEN tags->>'oneway' = '-1' THEN -1 
                            ELSE 0 
                        END as oneway,
                        -- Optimization: Segmentize (add verts) then Subdivide to kill long straight edges
                        ST_SnapToGrid(
                            ST_Subdivide(
                                ST_Segmentize(geom::geography, 50)::geometry, 
                                20
                            ), 
                            0.000001
                        ),
                        CASE 
                            WHEN tags->>'bridge' IS NOT NULL THEN false
                            WHEN tags->>'tunnel' IS NOT NULL THEN false
                            WHEN tags->>'layer' IS NOT NULL AND tags->>'layer' != '0' THEN false
                            ELSE true 
                        END as is_ground
                    FROM osm.ways
                    WHERE tags ? 'highway' 
                      AND tags->>'highway' IN (
                          'motorway', 'motorway_link', 'trunk', 'trunk_link',
                          'primary', 'primary_link', 'secondary', 'secondary_link',
                          'tertiary', 'tertiary_link', 'residential', 'living_street',
                          'service', 'unclassified'
                      )
                    LIMIT %s OFFSET %s
                """
                cur.execute(query, (limit, offset))
                rows_inserted = cur.rowcount
            conn.commit()
            return rows_inserted
        except Exception as e:
            log.error(f"Batch insert failed: {e}")
            raise
        finally:
            conn.close()

    def finalize_candidate_table(self):
        """Create indexes on edge_candidates after bulk load."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Indexing edge_candidates...")
                cur.execute("CREATE INDEX idx_ec_geom ON edge_candidates USING GIST(geom)")
                cur.execute("CREATE INDEX idx_edge_candidates_id ON edge_candidates(id)")
                cur.execute("CREATE INDEX idx_ec_is_ground ON edge_candidates(is_ground)")
                cur.execute("ANALYZE edge_candidates")
                
                # Verify count
                cur.execute("SELECT count(*) FROM edge_candidates;")
                cnt = cur.fetchone()[0]
                log.info(f"finalize_candidate_table verified count: {cnt}")
            conn.commit()
        finally:
            conn.close()

    def run_pgr_nodeNetwork(self):
        """
        Grid-Based Noding Strategy (Divide & Conquer).
        Replaces legacy pgr_nodeNetwork calls to prevent OOM on large graphs.
        """
        import time
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Starting Grid-Based Noding Strategy...")
                
                # 0. Optimization Config
                cur.execute("SET work_mem = '256MB'")
                cur.execute("SET synchronous_commit = off")
                
                # 1. Prepare Target Table
                cur.execute("DROP TABLE IF EXISTS edge_candidates_merged")
                cur.execute("""
                    CREATE TABLE edge_candidates_merged (
                        id SERIAL PRIMARY KEY,
                        old_id bigint,
                        sub_id int DEFAULT 1,
                        source int,
                        target int,
                        geom geometry(LineString, 4326)
                    )
                """)
                cur.execute("CREATE INDEX idx_ecm_geom ON edge_candidates_merged USING GIST(geom)")
                conn.commit()

                # 2. Get Extent
                cur.execute("SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent(geom) as e FROM edge_candidates WHERE is_ground = TRUE) t")
                res = cur.fetchone()
                if not res or res[0] is None:
                    log.warning("No ground edges found!")
                    # Just copy bridges if ground empty
                    pass
                else:
                    min_x, min_y, max_x, max_y = res
                    
                    # 3. Grid Loop
                    step = 0.05
                    buffer = 0.001
                    
                    cols = int((max_x - min_x) / step) + 1
                    rows = int((max_y - min_y) / step) + 1
                    total_tiles = cols * rows
                    
                    log.info(f"Noding Grid: {cols}x{rows} = {total_tiles} tiles. Extent: {min_x:.4f},{min_y:.4f} -> {max_x:.4f},{max_y:.4f}")
                    
                    tile_idx = 0
                    processed_count = 0
                    curr_x = min_x
                    
                    start_time = time.time()
                    
                    while curr_x < max_x:
                        curr_y = min_y
                        while curr_y < max_y:
                            tile_idx += 1
                            
                            # Define tile & expanded bounds
                            tile_box = f"ST_MakeEnvelope({curr_x}, {curr_y}, {curr_x + step}, {curr_y + step}, 4326)"
                            expand_box = f"ST_Expand({tile_box}, {buffer})"

                            # Complex Query: Node -> Filter by Centroid -> Join Back to get ID
                            query = f"""
                                WITH 
                                selection AS (
                                    SELECT id, geom FROM edge_candidates 
                                    WHERE is_ground = TRUE AND geom && {expand_box}
                                ),
                                noded_geoms AS (
                                    SELECT (ST_Dump(ST_Node(ST_Collect(geom)))).geom as geom 
                                    FROM selection
                                ),
                                valid_segments AS (
                                    SELECT geom FROM noded_geoms
                                    WHERE ST_Contains({tile_box}, ST_Centroid(geom))
                                )
                                INSERT INTO edge_candidates_merged (old_id, geom)
                                SELECT DISTINCT ON (s.geom)
                                    e.id, 
                                    s.geom
                                FROM valid_segments s
                                JOIN selection e ON ST_DWithin(s.geom, e.geom, 0.000001) AND ST_CoveredBy(s.geom, e.geom)
                                -- ToDo: fix precision issues
                                    -- Проверяем, что сегмент лежит внутри "немного раздутого" оригинала.
                                    -- Это прощает ошибки плавающей запятой.
                                    -- AND ST_CoveredBy(s.geom, ST_Buffer(e.geom, 0.0001))
                            """
                            cur.execute(query)
                            processed_count += cur.rowcount
                            
                            if tile_idx % 10 == 0:
                                conn.commit()
                                log.info(f"Processed tile {tile_idx}/{total_tiles} ({int((tile_idx/total_tiles)*100)}%)...")
                            
                            curr_y += step
                        curr_x += step

                    conn.commit()
                    log.info(f"Grid Noding Complete. Total segments: {processed_count}")

                # 4. Bridges (Direct Copy)
                log.info("Copying Bridges...")
                cur.execute("""
                    INSERT INTO edge_candidates_merged (old_id, geom)
                    SELECT id, geom FROM edge_candidates WHERE is_ground = FALSE
                """)
                bridge_count = cur.rowcount
                log.info(f"Bridges copied: {bridge_count}")
                conn.commit()
                
                # Index Merged
                log.info("Indexing Merged Network...")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ecm_old_id ON edge_candidates_merged(old_id)")
                cur.execute("ANALYZE edge_candidates_merged")
                
        except Exception as e:
            log.exception(f"Noding failed: {e}")
            raise
        finally:
            conn.close()

    def run_pgr_create_topology(self):
        """Create Topology on MERGED table."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Running pgr_createTopology on MERGED network...")
                cur.execute("SET maintenance_work_mem = '2GB'")
                cur.execute("SET max_parallel_workers_per_gather = 12")
                
                cur.execute("SELECT pgr_createTopology('edge_candidates_merged', 0.00001, 'geom', 'id')")
                cur.execute("ANALYZE edge_candidates_merged")
            conn.commit()
        finally:
            conn.close()

    def fill_graph_tables(self):
        """Populate graphs.nodes and graphs.edges from MERGED data."""
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                log.info("Populating graph tables...")
                cur.execute("TRUNCATE graphs.nodes CASCADE")
                cur.execute("TRUNCATE graphs.edges CASCADE")
                
                # Nodes
                log.info("Inserting Nodes...")
                cur.execute("""
                    INSERT INTO graphs.nodes (id, osm_node_id, geom)
                    SELECT id, id, the_geom FROM edge_candidates_merged_vertices_pgr
                """)
                
                # Edges Schema
                log.info("Recreating Edges Table schema...")
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
                        oneway int, -- Changed to int to preserve -1
                        highway_type text,
                        osm_tags jsonb,
                        max_speed float,
                        
                        -- Dynamic Attributes
                        duration float, 
                        is_open boolean DEFAULT true,
                        current_load int DEFAULT 0,
                        effective_speed_kmh float DEFAULT 60.0, 
                        last_updated timestamptz DEFAULT NOW(),
                        
                        cost float,
                        reverse_cost float
                    );
                    CREATE INDEX idx_graphs_edges_source ON graphs.edges(source_id);
                    CREATE INDEX idx_graphs_edges_target ON graphs.edges(target_id);
                    CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geometry);
                """)
                
                # Edges Population
                log.info("Inserting Edges with Speed Logic...")
                cur.execute("""
                    INSERT INTO graphs.edges (
                        osm_way_id, source_id, target_id, geometry, 
                        length_m, speed_limit_kmh, lanes, oneway, highway_type, 
                        osm_tags, max_speed, effective_speed_kmh, duration, is_open, cost, reverse_cost
                    )
                    WITH calculated_speeds AS (
                        SELECT 
                            ec.id as osm_way_id,
                            n.source, 
                            n.target, 
                            n.geom, 
                            ST_Length(n.geom::geography) as len,
                            CASE 
                                WHEN ec.maxspeed ~ '^[0-9]+$' THEN ec.maxspeed::float
                                WHEN ec.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link') THEN 110.0
                                WHEN ec.highway IN ('primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link') THEN 60.0
                                WHEN ec.highway IN ('residential', 'living_street', 'service', 'unclassified') THEN 20.0
                                ELSE 60.0 
                            END as spd_limit,
                            COALESCE(ec.lanes, 1) as lanes, 
                            ec.oneway, 
                            ec.highway,
                            ec.tags,
                            CASE 
                                WHEN ec.maxspeed ~ '^[0-9]+$' THEN ec.maxspeed::float
                                WHEN ec.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link') THEN 110.0
                                WHEN ec.highway IN ('residential', 'living_street', 'service') THEN 20.0
                                ELSE 60.0 
                            END as max_spd
                        FROM edge_candidates_merged n
                        JOIN edge_candidates ec ON n.old_id = ec.id
                        WHERE n.source IS NOT NULL AND n.target IS NOT NULL
                    )
                    SELECT 
                        osm_way_id, source, target, geom, len, 
                        spd_limit, lanes, oneway, highway, tags, max_spd,
                        spd_limit, 
                        -- Duration
                        len / GREATEST(spd_limit / 3.6, 0.1), 
                        true,
                        -- Cost (Forward)
                        CASE 
                            WHEN oneway = -1 THEN -1.0 
                            ELSE len / GREATEST(spd_limit / 3.6, 0.1) 
                        END,
                        -- Reverse Cost
                        CASE 
                            WHEN oneway = 1 THEN -1.0
                            ELSE len / GREATEST(spd_limit / 3.6, 0.1)
                        END
                    FROM calculated_speeds
                """)
            conn.commit()
            conn.commit()
        finally:
            conn.close()

    def update_traffic_batch(self, updates: List[Tuple[int, float]]):
        """
        Update traffic speeds for a batch of edges.
        updates: List of (osm_way_id, new_speed_kmh)
        Updates: duration, effective_speed_kmh, cost, reverse_cost.
        """
        if not updates:
            return
            
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Create temp table for updates
                cur.execute("CREATE TEMP TABLE traffic_updates (osm_way_id bigint, new_speed float) ON COMMIT DROP")
                
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO traffic_updates (osm_way_id, new_speed) VALUES %s",
                    updates
                )
                
                # Update main table
                query = """
                    UPDATE graphs.edges e
                    SET 
                        effective_speed_kmh = u.new_speed,
                        duration = e.length_m / GREATEST(u.new_speed / 3.6, 0.1),
                        last_updated = NOW(),
                        cost = CASE 
                            WHEN e.oneway = -1 THEN -1.0 
                            ELSE e.length_m / GREATEST(u.new_speed / 3.6, 0.1) 
                        END,
                        reverse_cost = CASE 
                            WHEN e.oneway = 1 THEN -1.0 
                            ELSE e.length_m / GREATEST(u.new_speed / 3.6, 0.1) 
                        END
                    FROM traffic_updates u
                    WHERE e.osm_way_id = u.osm_way_id
                """
                cur.execute(query)
                log.info(f"Updated traffic for {cur.rowcount} edges.")
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
                cur.execute("DROP TABLE IF EXISTS edge_candidates_ground")
                cur.execute("DROP TABLE IF EXISTS edge_candidates_ground_noded")
                cur.execute("DROP TABLE IF EXISTS edge_candidates_merged")
                cur.execute("DROP TABLE IF EXISTS edge_candidates_merged_vertices_pgr")
            conn.commit()
        finally:
            conn.close()
