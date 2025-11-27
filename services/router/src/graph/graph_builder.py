"""
GraphBuilder: Incremental graph building from OSM data

Automatically builds and updates routing graph when OSM data changes.
"""

import asyncpg
from loguru import logger
from typing import Optional, Tuple, Dict, List


class GraphBuilder:
    """Build and maintain routing graph from OSM data"""
    
    def __init__(self, db_pool: asyncpg.Pool, config: dict):
        self.db = db_pool
        self.config = config
        
        # Default speeds by highway type (km/h)
        self.default_speeds = {
            'motorway': 110,
            'motorway_link': 80,
            'trunk': 100,
            'trunk_link': 80,
            'primary': 80,
            'primary_link': 60,
            'secondary': 80,
            'secondary_link': 60,
            'tertiary': 60,
            'tertiary_link': 50,
            'residential': 60,
            'living_street': 20,
            'unclassified': 50,
            'service': 20,
            'road': 50,
            'track': 30,
        }
    
    async def ensure_graph_exists(self):
        """
        Check if graph exists, build if not
        
        Called on startup.
        """
        logger.info("Checking routing graph status...")
        async with self.db.acquire() as conn:
            # Check if graph is empty
            result = await conn.fetchrow(
                "SELECT COUNT(*) as count FROM graphs.edges"
            )
            
            if result['count'] == 0:
                logger.info("Graph is empty, building from OSM data...")
                await self._build_full_graph(conn)
            else:
                logger.info(f"Graph exists: {result['count']} edges")
    
    async def update_graph_for_ways(
        self,
        way_ids: List[int],
        bbox: Optional[Tuple[float, float, float, float]] = None
    ):
        """
        Update graph for specific OSM ways
        
        Called after downloading/updating OSM data.
        
        Args:
            way_ids: List of OSM way IDs that were updated
            bbox: Optional bounding box filter
        """
        if not way_ids:
            return
        
        logger.debug(f"Updating graph for {len(way_ids)} ways")
        
        async with self.db.acquire() as conn:
            # Step 1: Ensure nodes exist for way endpoints
            await self._ensure_nodes_for_ways(conn, way_ids)
            
            # Step 2: Update/create edges for ways
            await self._update_edges_for_ways(conn, way_ids)
            
            # Step 3: Update barriers if needed
            if bbox:
                await self._update_barriers_in_bbox(conn, bbox)
    
    async def _build_full_graph(self, conn):
        """Build complete graph from all OSM data"""
        logger.info("Building full graph from OSM data...")
        
        # Step 1: Build all nodes from way endpoints
        logger.info("Step 1/4: Building nodes from way endpoints...")
        await self._build_all_nodes(conn)
        
        # Step 2: Build all edges
        logger.info("Step 2/4: Building edges from ways...")
        await self._build_all_edges(conn)
        
        # Step 3: Apply barriers
        logger.info("Step 3/4: Applying barriers to nodes...")
        await self._apply_all_barriers(conn)
        
        # Step 4: Parse turn restrictions
        logger.info("Step 4/4: Parsing turn restrictions...")
        await self._parse_all_turn_restrictions(conn)
        
        # Get stats
        stats = await conn.fetchrow("""
            SELECT 
                (SELECT COUNT(*) FROM graphs.nodes) as nodes,
                (SELECT COUNT(*) FROM graphs.edges) as edges
        """)
        
        logger.info(
            f"✓ Graph built: {stats['nodes']:,} nodes, {stats['edges']:,} edges"
        )
    
    async def _build_all_nodes(self, conn):
        """Extract all unique nodes from way endpoints (batch processing)"""
        # Get total ways count
        total = await conn.fetchval("SELECT COUNT(*) FROM osm.ways")
        logger.info(f"Processing {total:,} ways in batches...")
        
        batch_size = 5000
        processed = 0
        
        for offset in range(0, total, batch_size):
            # Process batch
            query = f"""
                WITH batch_ways AS (
                    SELECT osm_id, geom
                    FROM osm.ways
                    WHERE geom IS NOT NULL
                    ORDER BY osm_id
                    LIMIT {batch_size} OFFSET {offset}
                ),
                endpoints AS (
                    SELECT ST_StartPoint(geom) as geom FROM batch_ways
                    UNION ALL
                    SELECT ST_EndPoint(geom) as geom FROM batch_ways
                )
                INSERT INTO graphs.nodes (
                    osm_node_id,
                    lat,
                    lon,
                    geometry,
                    type
                )
                SELECT DISTINCT
                    abs(hashtext(ST_AsText(geom)))::BIGINT,
                    ST_Y(geom),
                    ST_X(geom),
                    geom,
                    'endpoint'
                FROM endpoints
                ON CONFLICT (osm_node_id) DO NOTHING
            """
            
            await conn.execute(query)
            processed += batch_size
            logger.debug(f"Nodes: processed {min(processed, total):,}/{total:,} ways")
        
        # Log final count
        count = await conn.fetchval("SELECT COUNT(*) FROM graphs.nodes")
        logger.info(f"Created {count:,} nodes")
    
    async def _build_all_edges(self, conn):
        """Create edges from all ways (batch processing)"""
        # Get total drivable ways count
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM osm.ways WHERE highway IS NOT NULL"
        )
        logger.info(f"Processing {total:,} drivable ways in batches...")
        
        batch_size = 5000
        processed = 0
        
        for offset in range(0, total, batch_size):
            query = f"""
                WITH batch_ways AS (
                    SELECT *
                    FROM osm.ways
                    WHERE highway IS NOT NULL
                    ORDER BY osm_id
                    LIMIT {batch_size} OFFSET {offset}
                )
                INSERT INTO graphs.edges (
                    osm_way_id,
                    start_node_id,
                    end_node_id,
                    geometry,
                    highway_type,
                    name,
                    lanes,
                    speed_limit_kmh,
                    oneway,
                    access_type,
                    is_restricted,
                    base_capacity,
                    length_m
                )
                SELECT 
                    w.osm_id,
                    ns.id,
                    ne.id,
                    w.geom,
                    w.highway,
                    w.name,
                    COALESCE(w.lanes, 1),
                    COALESCE(
                        CASE 
                            WHEN w.maxspeed ~ '^[0-9]+$' THEN w.maxspeed::INT
                            WHEN w.maxspeed = 'RU:urban' THEN 60
                            ELSE NULL
                        END,
                        {self._get_default_speed_case()}
                    ),
                    w.oneway,
                    w.access,
                    CASE WHEN w.access IN ('private', 'no') THEN true ELSE false END,
                    100,
                    ST_Length(ST_Transform(w.geom, 3857)) as length_m
                FROM batch_ways w
                LEFT JOIN graphs.nodes ns ON ns.osm_node_id = abs(hashtext(ST_AsText(ST_StartPoint(w.geom))))::BIGINT
                LEFT JOIN graphs.nodes ne ON ne.osm_node_id = abs(hashtext(ST_AsText(ST_EndPoint(w.geom))))::BIGINT
                WHERE ns.id IS NOT NULL AND ne.id IS NOT NULL
                ON CONFLICT (osm_way_id, start_node_id, end_node_id) DO NOTHING
            """
            
            await conn.execute(query)
            processed += batch_size
            logger.debug(f"Edges: processed {min(processed, total):,}/{total:,} ways")
        
        # Log final count
        count = await conn.fetchval("SELECT COUNT(*) FROM graphs.edges")
        logger.info(f"Created {count:,} edges")
    
    def _get_default_speed_case(self) -> str:
        """Generate CASE statement for default speeds"""
        cases = []
        for highway_type, speed in self.default_speeds.items():
            cases.append(f"WHEN w.highway = '{highway_type}' THEN {speed}")
        cases.append("ELSE 50")
        return "CASE " + " ".join(cases) + " END"
    
    async def _apply_all_barriers(self, conn):
        """Mark all nodes with barriers"""
        query = """
            WITH barrier_nodes AS (
                SELECT DISTINCT ON (n.id)
                    n.id as node_id,
                    b.barrier_type
                FROM osm.barriers b
                CROSS JOIN LATERAL (
                    SELECT id, geometry
                    FROM graphs.nodes
                    ORDER BY geometry <-> b.geom
                    LIMIT 1
                ) n
                WHERE ST_DWithin(b.geom, n.geometry, 0.0001)
            )
            UPDATE graphs.nodes n
            SET 
                has_barrier = true,
                barrier_type = bn.barrier_type
            FROM barrier_nodes bn
            WHERE n.id = bn.node_id
        """
        
        result = await conn.execute(query)
        logger.debug(f"Applied barriers: {result}")
    
    async def _parse_all_turn_restrictions(self, conn):
        """Convert all OSM turn restrictions to graph format"""
        query = """
            WITH osm_restrictions AS (
                SELECT 
                    tr.restriction_type,
                    ef.id as from_edge,
                    et.id as to_edge,
                    vn.id as via_node_id
                FROM osm.turn_restrictions tr
                LEFT JOIN graphs.edges ef ON ef.osm_way_id = tr.from_way
                LEFT JOIN graphs.edges et ON et.osm_way_id = tr.to_way
                LEFT JOIN graphs.nodes vn ON abs(hashtext(ST_AsText(
                    ST_SetSRID(ST_MakePoint(0, 0), 4326)
                )))::BIGINT = tr.via_node
                WHERE tr.from_way IS NOT NULL 
                  AND tr.to_way IS NOT NULL
            )
            INSERT INTO graphs.turn_restrictions (
                from_edge,
                to_edge,
                via_node,
                restriction_type,
                cost
            )
            SELECT 
                from_edge,
                to_edge,
                via_node_id,
                restriction_type,
                CASE 
                    WHEN restriction_type LIKE 'no_%' THEN 1000000.0
                    WHEN restriction_type LIKE 'only_%' THEN 0.1
                    ELSE 100.0
                END
            FROM osm_restrictions
            WHERE from_edge IS NOT NULL AND to_edge IS NOT NULL
            ON CONFLICT DO NOTHING
        """
        
        result = await conn.execute(query)
        logger.debug(f"Parsed turn restrictions: {result}")
    
    async def _ensure_nodes_for_ways(self, conn, way_ids: List[int]):
        """Ensure nodes exist for given way endpoints"""
        # For incremental updates, just ensure nodes exist
        query = """
            WITH way_endpoints AS (
                SELECT DISTINCT
                    ST_StartPoint(geom) as geom
                FROM osm.ways
                WHERE osm_id = ANY($1)
                UNION
                SELECT DISTINCT
                    ST_EndPoint(geom) as geom
                FROM osm.ways
                WHERE osm_id = ANY($1)
            )
            INSERT INTO graphs.nodes (osm_node_id, lat, lon, geometry, type)
            SELECT 
                abs(hashtext(ST_AsText(geom)))::BIGINT,
                ST_Y(geom),
                ST_X(geom),
                geom,
                'endpoint'
            FROM way_endpoints
            ON CONFLICT (osm_node_id) DO NOTHING
        """
        
        await conn.execute(query, way_ids)
    
    async def _update_edges_for_ways(self, conn, way_ids: List[int]):
        """Update edges for given ways"""
        query = f"""
            INSERT INTO graphs.edges (
                osm_way_id, start_node_id, end_node_id, geometry,
                highway_type, name, lanes, speed_limit_kmh, oneway,
                access_type, is_restricted, base_capacity
            )
            SELECT 
                w.osm_id,
                ns.id,
                ne.id,
                w.geom,
                w.highway,
                w.name,
                COALESCE(w.lanes, 1),
                COALESCE(
                    CASE 
                        WHEN w.maxspeed ~ '^[0-9]+$' THEN w.maxspeed::INT
                        WHEN w.maxspeed = 'RU:urban' THEN 60
                        ELSE NULL
                    END,
                    {self._get_default_speed_case()}
                ),
                w.oneway,
                w.access,
                CASE WHEN w.access IN ('private', 'no') THEN true ELSE false END,
                GREATEST(100, (ST_Length(ST_Transform(w.geom, 3857)) / 5.0)::INT * COALESCE(w.lanes, 1))
            FROM osm.ways w
            LEFT JOIN graphs.nodes ns ON ST_Equals(ST_StartPoint(w.geom), ns.geometry)
            LEFT JOIN graphs.nodes ne ON ST_Equals(ST_EndPoint(w.geom), ne.geometry)
            WHERE w.osm_id = ANY($1)
              AND w.highway IS NOT NULL
              AND ns.id IS NOT NULL
              AND ne.id IS NOT NULL
            ON CONFLICT (osm_way_id, start_node_id, end_node_id) DO UPDATE SET
                geometry = EXCLUDED.geometry,
                highway_type = EXCLUDED.highway_type,
                name = EXCLUDED.name,
                lanes = EXCLUDED.lanes,
                speed_limit_kmh = EXCLUDED.speed_limit_kmh,
                oneway = EXCLUDED.oneway,
                access_type = EXCLUDED.access_type,
                is_restricted = EXCLUDED.is_restricted,
                base_capacity = EXCLUDED.base_capacity
        """
        
        await conn.execute(query, way_ids)
    
    async def _update_barriers_in_bbox(
        self,
        conn,
        bbox: Tuple[float, float, float, float]
    ):
        """Update barriers for nodes in bbox"""
        west, south, east, north = bbox
        
        query = f"""
            WITH barrier_nodes AS (
                SELECT DISTINCT ON (n.id)
                    n.id as node_id,
                    b.barrier_type
                FROM osm.barriers b
                CROSS JOIN LATERAL (
                    SELECT id, geometry
                    FROM graphs.nodes
                    WHERE geometry && ST_MakeEnvelope({west}, {south}, {east}, {north}, 4326)
                    ORDER BY geometry <-> b.geom
                    LIMIT 1
                ) n
                WHERE ST_DWithin(b.geom, n.geometry, 0.0001)
                  AND b.geom && ST_MakeEnvelope({west}, {south}, {east}, {north}, 4326)
            )
            UPDATE graphs.nodes n
            SET 
                has_barrier = true,
                barrier_type = bn.barrier_type
            FROM barrier_nodes bn
            WHERE n.id = bn.node_id
        """
        
        await conn.execute(query)
