"""
GraphBuilder: построение графа маршрутизации из OSM данных.

Основные задачи:
1. Синхронизация конфига YAML → graphs.system_config
2. Разбиение osm.ways на graphs.edges в точках пересечения
3. Применение default_speeds из конфига
4. Интеграция барьеров osm.barriers → graphs.nodes
5. Интеграция turn_restrictions osm → graphs
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import asyncpg
import yaml


logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Построитель графа маршрутизации из данных OSM.
    
    Workflow:
    1. Загрузка конфига traffic_config.yaml
    2. Синхронизация конфига в graphs.system_config
    3. Поиск пересечений (intersection nodes)
    4. Разбиение ways на edges в точках пересечения
    5. Применение default_speeds где нет maxspeed
    6. Перенос барьеров в graph nodes
    7. Перенос turn_restrictions в graphs
    """
    
    def __init__(
        self,
        config_path: str = "configs/router/traffic_config.yaml",
        db_dsn: str = "postgresql://diplom:diplom_pass@localhost:5432/osm"
    ):
        """
        Args:
            config_path: Путь к traffic_config.yaml
            db_dsn: DSN подключения к PostgreSQL
        """
        self.config_path = Path(config_path)
        self.db_dsn = db_dsn
        self.config: Optional[Dict] = None
        self.pool: Optional[asyncpg.Pool] = None
    
    async def initialize(self):
        """Инициализация: загрузка конфига, подключение к БД."""
        logger.info("Initializing GraphBuilder...")
        
        # Load config
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        logger.info(f"Loaded config: {self.config_path}")
        
        # Connect to DB
        self.pool = await asyncpg.create_pool(
            dsn=self.db_dsn,
            min_size=2,
            max_size=10
        )
        
        logger.info("Connected to database")
    
    async def close(self):
        """Закрытие соединений."""
        if self.pool:
            await self.pool.close()
            logger.info("Database connections closed")
    
    async def build_graph(self):
        """
        Главная функция: полное построение графа.
        
        Sequence:
        1. sync_config_to_db()
        2. find_and_create_intersection_nodes()
        3. split_ways_into_edges()
        4. apply_default_speeds()
        5. populate_barrier_nodes()
        6. populate_turn_restrictions()
        """
        logger.info("=" * 60)
        logger.info("Starting graph build...")
        logger.info("=" * 60)
        
        try:
            await self.sync_config_to_db()
            await self.find_and_create_intersection_nodes()
            await self.split_ways_into_edges()
            await self.apply_default_speeds()
            await self.populate_barrier_nodes()
            await self.populate_turn_restrictions()
            
            logger.info("=" * 60)
            logger.info("Graph build completed successfully!")
            logger.info("=" * 60)
            
            await self.print_statistics()
        
        except Exception as e:
            logger.error(f"Graph build failed: {e}", exc_info=True)
            raise
    
    async def sync_config_to_db(self):
        """
        Синхронизация конфига YAML → graphs.system_config.
        
        Updates:
        - length_auto_m
        - safe_distance_s
        - speed_tolerance_kmh (из RU профиля)
        - min_speed_kmh (из RU профиля)
        """
        logger.info("Syncing config to graphs.system_config...")
        
        physics = self.config['vehicle_physics']
        speed_rules = self.config['speed_rules']
        current_region = speed_rules['current_region']
        region_profile = speed_rules['profiles'][current_region]
        
        params = [
            ('length_auto_m', physics['length_auto_m']),
            ('safe_distance_s', physics['safe_distance_s']),
            ('speed_tolerance_kmh', region_profile['tolerance_kmh']),
            ('min_speed_kmh', region_profile['min_speed_kmh'])
        ]
        
        async with self.pool.acquire() as conn:
            for key, value in params:
                await conn.execute(
                    """
                    INSERT INTO graphs.system_config (key_name, value_numeric)
                    VALUES ($1, $2)
                    ON CONFLICT (key_name) DO UPDATE
                    SET value_numeric = EXCLUDED.value_numeric
                    """,
                    key, float(value)
                )
                logger.info(f"  {key} = {value}")
        
        logger.info("Config synced successfully")
    
    async def find_and_create_intersection_nodes(self):
        """
        Находит пересечения (nodes используемые 2+ ways) и создает graphs.nodes.
        
        Algorithm:
        1. Extract all points from osm.ways (start, end, + intermediate via ST_DumpPoints)
        2. Find points used by 2+ ways (ST_Equals with tolerance)
        3. INSERT INTO graphs.nodes with is_intersection=true/false
        4. Also add all start/end points as potential nodes
        """
        logger.info("Finding and creating intersection nodes...")
        
        async with self.pool.acquire() as conn:
            # Clear old nodes first
            await conn.execute("TRUNCATE graphs.nodes CASCADE")
            logger.info("Cleared old graph nodes")
            
            # Step 1: Create temporary table with all way endpoints
            await conn.execute("""
                CREATE TEMP TABLE IF NOT EXISTS way_endpoints AS
                SELECT 
                    osm_id as way_id,
                    ST_StartPoint(geom) as geom,
                    'start' as point_type
                FROM osm.ways
                WHERE highway IS NOT NULL
                
                UNION ALL
                
                SELECT 
                    osm_id as way_id,
                    ST_EndPoint(geom) as geom,
                    'end' as point_type
                FROM osm.ways
                WHERE highway IS NOT NULL
            """)
            
            # Get count
            endpoints_count = await conn.fetchval(
                "SELECT COUNT(*) FROM way_endpoints"
            )
            logger.info(f"Extracted {endpoints_count} endpoints from ways")
            
            # Step 2: Find intersection points (used by 2+ ways)
            # Use ST_SnapToGrid to group nearby points (tolerance ~1m)
            await conn.execute("""
                CREATE TEMP TABLE IF NOT EXISTS intersection_points AS
                SELECT 
                    ST_SnapToGrid(geom, 0.00001) as geom_snapped,
                    COUNT(DISTINCT way_id) as way_count,
                    array_agg(DISTINCT way_id) as way_ids
                FROM way_endpoints
                GROUP BY ST_SnapToGrid(geom, 0.00001)
                HAVING COUNT(DISTINCT way_id) >= 2
            """)
            
            intersections_count = await conn.fetchval(
                "SELECT COUNT(*) FROM intersection_points"
            )
            logger.info(f"Found {intersections_count} intersection points")
            
            # Step 3: Insert intersection nodes into graphs.nodes
            await conn.execute("""
                INSERT INTO graphs.nodes (geom, lat, lon, type, is_intersection)
                SELECT 
                    geom_snapped as geom,
                    ST_Y(geom_snapped) as lat,
                    ST_X(geom_snapped) as lon,
                    'intersection' as type,
                    true as is_intersection
                FROM intersection_points
            """)
            
            logger.info(f"Inserted {intersections_count} intersection nodes")
            
            # Step 4: Insert non-intersection endpoints (degree 1)
            await conn.execute("""
                INSERT INTO graphs.nodes (geom, lat, lon, type, is_intersection)
                SELECT DISTINCT
                    ST_SnapToGrid(e.geom, 0.00001) as geom,
                    ST_Y(ST_SnapToGrid(e.geom, 0.00001)) as lat,
                    ST_X(ST_SnapToGrid(e.geom, 0.00001)) as lon,
                    'endpoint' as type,
                    false as is_intersection
                FROM way_endpoints e
                WHERE NOT EXISTS (
                    SELECT 1 FROM intersection_points i
                    WHERE ST_DWithin(ST_SnapToGrid(e.geom, 0.00001), i.geom_snapped, 0.000001)
                )
            """)
            
            endpoints_added = await conn.fetchval(
                "SELECT COUNT(*) FROM graphs.nodes WHERE is_intersection = false"
            )
            logger.info(f"Inserted {endpoints_added} endpoint nodes")
            
            # Step 5: Create spatial index
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_graphs_nodes_geom ON graphs.nodes USING GIST (geom)"
            )
            
            total_nodes = await conn.fetchval("SELECT COUNT(*) FROM graphs.nodes")
            logger.info(f"Total graph nodes created: {total_nodes}")
            
            # Cleanup temp tables
            await conn.execute("DROP TABLE IF EXISTS way_endpoints CASCADE")
            await conn.execute("DROP TABLE IF EXISTS intersection_points CASCADE")
    
    async def split_ways_into_edges(self):
        """
        Разбивает osm.ways на graphs.edges в точках пересечения.
        
        Algorithm:
        1. For each way in osm.ways:
        2.   Find graph nodes that snap to way geometry
        3.   Split way LineString at these points using ST_LineSubstring
        4.   INSERT INTO graphs.edges (source, target, geom, ...)
        
        Trigger graphs.calculate_edge_attributes() автоматически вычислит:
        - length_m, unstamped_speed_kmh, capacity
        """
        logger.info("Splitting ways into edges...")
        
        async with self.pool.acquire() as conn:
            # Clear old edges
            await conn.execute("TRUNCATE graphs.edges CASCADE")
            logger.info("Cleared old graph edges")
            
            # Get all ways
            ways = await conn.fetch("""
                SELECT 
                    osm_id, geom, highway, lanes, maxspeed,
                    oneway, access, motor_vehicle, service, tags
                FROM osm.ways
                WHERE highway IS NOT NULL
                ORDER BY osm_id
            """)
            
            logger.info(f"Processing {len(ways)} ways...")
            
            edges_created = 0
            ways_processed = 0
            
            for way in ways:
                way_id = way['osm_id']
                way_geom = way['geom']
                
                # Parse maxspeed to integer (km/h)
                maxspeed_kmh = None
                if way['maxspeed']:
                    try:
                        maxspeed_str = way['maxspeed'].replace(' km/h', '').replace('km/h', '')
                        maxspeed_kmh = int(maxspeed_str)
                    except (ValueError, AttributeError):
                        maxspeed_kmh = None
                
                # Parse lanes
                lanes = way['lanes'] if way['lanes'] else 1
                
                # Parse oneway
                oneway = way['oneway'] in ('yes', '1', 'true', '-1') if way['oneway'] else False
                
                # Find nodes that snap to this way (start, end, intersections along way)
                # Use ST_DWithin to find nearby nodes
                nodes_on_way = await conn.fetch("""
                    SELECT 
                        id, geom,
                        ST_LineLocatePoint($1, geom) as fraction
                    FROM graphs.nodes
                    WHERE ST_DWithin(geom, $1, 0.00002)  -- ~2m tolerance
                    ORDER BY ST_LineLocatePoint($1, geom)
                """, way_geom)
                
                if len(nodes_on_way) < 2:
                    # Way has no intersections, create single edge
                    start_node_id = await self._get_or_create_node_at_point(
                        conn, way_geom, 'start'
                    )
                    end_node_id = await self._get_or_create_node_at_point(
                        conn, way_geom, 'end'
                    )
                    
                    # Skip self-loops (roundabouts, circular ways)
                    if start_node_id == end_node_id:
                        logger.debug(f"Skipping self-loop way {way_id}")
                        continue
                    
                    await conn.execute("""
                        INSERT INTO graphs.edges (
                            source, target, geom, osm_way_id, highway, lanes,
                            maxspeed_kmh, oneway, access_type, motor_vehicle, service
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                        start_node_id, end_node_id, way_geom, way_id,
                        way['highway'], lanes, maxspeed_kmh, oneway,
                        way['access'], way['motor_vehicle'], way['service']
                    )
                    edges_created += 1
                    
                else:
                    # Split way into segments between consecutive nodes
                    for i in range(len(nodes_on_way) - 1):
                        source_node = nodes_on_way[i]
                        target_node = nodes_on_way[i + 1]
                        
                        fraction_start = source_node['fraction']
                        fraction_end = target_node['fraction']
                        
                        # Skip if fractions are identical (nodes at same location)
                        if abs(fraction_end - fraction_start) < 0.001:
                            continue
                        
                        # Skip self-loops
                        if source_node['id'] == target_node['id']:
                            continue
                        
                        # Extract segment geometry
                        segment_geom = await conn.fetchval("""
                            SELECT ST_LineSubstring($1, $2, $3)
                        """, way_geom, fraction_start, fraction_end)
                        
                        # Insert edge
                        await conn.execute("""
                            INSERT INTO graphs.edges (
                                source, target, geom, osm_way_id, highway, lanes,
                                maxspeed_kmh, oneway, access_type, motor_vehicle, service
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        """,
                            source_node['id'], target_node['id'], segment_geom, way_id,
                            way['highway'], lanes, maxspeed_kmh, oneway,
                            way['access'], way['motor_vehicle'], way['service']
                        )
                        edges_created += 1
                
                ways_processed += 1
                
                if ways_processed % 100 == 0:
                    logger.info(f"  Processed {ways_processed}/{len(ways)} ways, created {edges_created} edges")
            
            logger.info(f"Created {edges_created} edges from {ways_processed} ways")
    
    async def _get_or_create_node_at_point(
        self, 
        conn: asyncpg.Connection, 
        way_geom, 
        point_type: str
    ) -> int:
        """
        Get or create node at start/end point of way geometry.
        
        Args:
            conn: Database connection
            way_geom: Way LineString geometry
            point_type: 'start' or 'end'
        
        Returns:
            Node ID
        """
        if point_type == 'start':
            point = await conn.fetchval("SELECT ST_StartPoint($1)", way_geom)
        else:
            point = await conn.fetchval("SELECT ST_EndPoint($1)", way_geom)
        
        # Find existing node nearby
        existing_node = await conn.fetchrow("""
            SELECT id FROM graphs.nodes
            WHERE ST_DWithin(geom, $1, 0.00001)  -- ~1m
            ORDER BY ST_Distance(geom, $1)
            LIMIT 1
        """, point)
        
        if existing_node:
            return existing_node['id']
        
        # Create new node
        node_id = await conn.fetchval("""
            INSERT INTO graphs.nodes (geom, lat, lon, type, is_intersection)
            VALUES ($1, ST_Y($1), ST_X($1), 'endpoint', false)
            RETURNING id
        """, point)
        
        return node_id
    
    async def apply_default_speeds(self):
        """
        Применяет default_speeds из конфига для edges без maxspeed_kmh.
        
        Priority: OSM maxspeed > config default_speeds > 50 km/h fallback
        """
        logger.info("Applying default speeds...")
        
        default_speeds = self.config['default_speeds']
        
        async with self.pool.acquire() as conn:
            for highway_type, speed in default_speeds.items():
                result = await conn.execute(
                    """
                    UPDATE graphs.edges
                    SET maxspeed_kmh = $1
                    WHERE highway = $2 AND maxspeed_kmh IS NULL
                    """,
                    speed, highway_type
                )
                
                count = int(result.split()[-1]) if 'UPDATE' in result else 0
                if count > 0:
                    logger.info(f"  {highway_type}: {speed} km/h → {count} edges")
            
            # Fallback for unknown highway types
            result = await conn.execute(
                """
                UPDATE graphs.edges
                SET maxspeed_kmh = 50
                WHERE maxspeed_kmh IS NULL
                """
            )
            
            count = int(result.split()[-1]) if 'UPDATE' in result else 0
            if count > 0:
                logger.info(f"  fallback: 50 km/h → {count} edges")
        
        logger.info("Default speeds applied")
    
    async def populate_barrier_nodes(self):
        """
        Переносит барьеры osm.barriers → graphs.nodes.
        
        Algorithm:
        1. For each barrier in osm.barriers:
        2.   Find nearest graph node (ST_DWithin 10m tolerance)
        3.   UPDATE graphs.nodes SET has_barrier=true, barrier_type, barrier_penalty_sec
        
        Barrier penalties:
        - gate: 30 sec
        - lift_gate: 45 sec
        - bollard: 60 sec (hard to pass)
        - swing_gate: 30 sec
        - block: 120 sec (very hard)
        - wicket_gate: 20 sec (easy)
        """
        logger.info("Populating barrier nodes...")
        
        barrier_penalties = {
            'gate': 30,
            'lift_gate': 45,
            'bollard': 60,
            'swing_gate': 30,
            'block': 120,
            'wicket_gate': 20
        }
        
        async with self.pool.acquire() as conn:
            # Get barriers
            barriers = await conn.fetch(
                """
                SELECT id, barrier_type, geom
                FROM osm.barriers
                WHERE barrier_type IS NOT NULL
                """
            )
            
            logger.info(f"Found {len(barriers)} barriers")
            
            updated = 0
            for barrier in barriers:
                barrier_type = barrier['barrier_type']
                penalty = barrier_penalties.get(barrier_type, 60)  # default 60 sec
                
                # Find nearest node (10m tolerance)
                result = await conn.execute(
                    """
                    UPDATE graphs.nodes
                    SET 
                        has_barrier = true,
                        barrier_type = $1,
                        barrier_penalty_sec = $2
                    WHERE id IN (
                        SELECT id
                        FROM graphs.nodes
                        WHERE ST_DWithin(geom, $3, 0.0001)  -- ~10m in degrees
                        ORDER BY ST_Distance(geom, $3)
                        LIMIT 1
                    )
                    """,
                    barrier_type, penalty, barrier['geom']
                )
                
                if 'UPDATE 1' in result:
                    updated += 1
            
            logger.info(f"Updated {updated} nodes with barrier info")
    
    async def populate_turn_restrictions(self):
        """
        Переносит turn_restrictions osm → graphs.turn_restrictions.
        
        Algorithm:
        1. For each restriction in osm.turn_restrictions:
        2.   Map osm way_ids → graph edge_ids (via osm_way_id column)
        3.   Map osm via_node_id → graph node_id (spatial query)
        4.   INSERT INTO graphs.turn_restrictions (from_edge, to_edge, via_node, restriction_type, cost)
        
        Cost mapping:
        - no_*: 1000000 (prohibited)
        - only_*: handled separately (all other turns prohibited)
        """
        logger.info("Populating turn restrictions...")
        
        async with self.pool.acquire() as conn:
            # Clear old restrictions
            await conn.execute("TRUNCATE graphs.turn_restrictions CASCADE")
            
            restrictions = await conn.fetch("""
                SELECT 
                    osm_relation_id,
                    restriction_type,
                    from_way_id,
                    via_node_id,
                    via_way_id,
                    to_way_id
                FROM osm.turn_restrictions
            """)
            
            logger.info(f"Found {len(restrictions)} turn restrictions from OSM")
            
            inserted = 0
            skipped = 0
            
            for r in restrictions:
                # Only handle node-based restrictions (via_node_id)
                # Way-based restrictions (via_way_id) are rare and complex
                if not r['via_node_id']:
                    logger.debug(f"Skipping way-based restriction {r['osm_relation_id']}")
                    skipped += 1
                    continue
                
                # Map OSM way_ids to graph edge_ids
                from_edges = await conn.fetch("""
                    SELECT id FROM graphs.edges
                    WHERE osm_way_id = $1
                """, r['from_way_id'])
                
                to_edges = await conn.fetch("""
                    SELECT id FROM graphs.edges
                    WHERE osm_way_id = $1
                """, r['to_way_id'])
                
                # Find via_node in graph by finding intersection of from_way and to_way
                # Use edges' source/target nodes that match both ways
                via_node_graph = await conn.fetchrow("""
                    SELECT DISTINCT n.id
                    FROM graphs.nodes n
                    INNER JOIN graphs.edges e1 ON (e1.source = n.id OR e1.target = n.id)
                    INNER JOIN graphs.edges e2 ON (e2.source = n.id OR e2.target = n.id)
                    WHERE e1.osm_way_id = $1
                      AND e2.osm_way_id = $2
                      AND n.is_intersection = true
                    LIMIT 1
                """, r['from_way_id'], r['to_way_id'])
                
                if not via_node_graph:
                    logger.debug(f"Graph node not found near OSM node {r['via_node_id']}, skipping")
                    skipped += 1
                    continue
                
                # Determine cost
                restriction_type = r['restriction_type']
                if restriction_type.startswith('no_'):
                    cost = 1000000.0  # Prohibited
                elif restriction_type.startswith('only_'):
                    cost = 0.0  # This turn is allowed, others will be prohibited later
                else:
                    cost = 1000.0  # Discouraged
                
                # Insert restrictions for all combinations of from_edge→to_edge
                for from_edge in from_edges:
                    for to_edge in to_edges:
                        try:
                            await conn.execute("""
                                INSERT INTO graphs.turn_restrictions (
                                    from_edge, to_edge, via_node, restriction_type, cost
                                )
                                VALUES ($1, $2, $3, $4, $5)
                                ON CONFLICT DO NOTHING
                            """,
                                from_edge['id'], to_edge['id'], via_node_graph['id'],
                                restriction_type, cost
                            )
                            inserted += 1
                        except Exception as e:
                            logger.debug(f"Failed to insert restriction: {e}")
                            continue
            
            logger.info(f"Inserted {inserted} turn restrictions into graphs.turn_restrictions")
            logger.info(f"Skipped {skipped} restrictions (way-based or mapping failed)")
    
    async def print_statistics(self):
        """Выводит статистику графа."""
        logger.info("=" * 60)
        logger.info("Graph Statistics:")
        logger.info("=" * 60)
        
        async with self.pool.acquire() as conn:
            # Nodes
            nodes_total = await conn.fetchval("SELECT COUNT(*) FROM graphs.nodes")
            nodes_intersection = await conn.fetchval(
                "SELECT COUNT(*) FROM graphs.nodes WHERE is_intersection = true"
            )
            nodes_barrier = await conn.fetchval(
                "SELECT COUNT(*) FROM graphs.nodes WHERE has_barrier = true"
            )
            
            logger.info(f"Nodes: {nodes_total} total")
            logger.info(f"  - Intersections: {nodes_intersection}")
            logger.info(f"  - With barriers: {nodes_barrier}")
            
            # Edges
            edges_total = await conn.fetchval("SELECT COUNT(*) FROM graphs.edges")
            edges_oneway = await conn.fetchval(
                "SELECT COUNT(*) FROM graphs.edges WHERE oneway = true"
            )
            
            logger.info(f"Edges: {edges_total} total")
            logger.info(f"  - Oneway: {edges_oneway}")
            
            # Turn restrictions
            restrictions = await conn.fetchval("SELECT COUNT(*) FROM graphs.turn_restrictions")
            logger.info(f"Turn restrictions: {restrictions}")
            
            logger.info("=" * 60)


async def main():
    """Entry point для запуска GraphBuilder."""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] {%(name)s} %(levelname)s: %(message)s',
        datefmt='%Y.%m.%d %H:%M:%S'
    )
    
    builder = GraphBuilder()
    
    try:
        await builder.initialize()
        await builder.build_graph()
    finally:
        await builder.close()


if __name__ == "__main__":
    asyncio.run(main())
