import asyncio
import asyncpg
from services.common.config import load_settings

async def main():
    settings = load_settings()
    dsn = f"postgresql://{settings.db.user}:{settings.db.password}@{settings.db.host}:{settings.db.port}/{settings.db.name}"
    
    print(f"Connecting to {dsn}...")
    conn = await asyncpg.connect(dsn)
    
    # Coordinates from user trace
    start_lat, start_lon = 55.814839927540135, 37.71078922535523
    end_lat, end_lon = 55.78103219342168, 37.61044716472236
    
    # 1. Snap
    print("\n--- Snapping Start Point ---")
    start_node = await snap_node(conn, start_lat, start_lon)
    print(f"Start Node: {start_node}")
    
    print("\n--- Snapping End Point ---")
    end_node = await snap_node(conn, end_lat, end_lon)
    print(f"End Node: {end_node}")
    
    if start_node and end_node:
        # 2. Check Outgoing Edges
        print(f"\n--- Checking Outgoing Edges from Start {start_node} ---")
        rows = await conn.fetch("SELECT * FROM graphs.edges WHERE source_id = $1 OR (target_id = $1 AND oneway = false) LIMIT 5", start_node)
        for r in rows:
            print(f"Edge {r['id']}: Source={r['source_id']}, Target={r['target_id']}, Oneway={r['oneway']}, Type={r['highway_type']}")
            
        if not rows:
            print("WARNING: Start Node has NO outgoing edges!")

        # 3. Check Incoming Edges
        print(f"\n--- Checking Incoming Edges to End {end_node} ---")
        rows = await conn.fetch("SELECT * FROM graphs.edges WHERE target_id = $1 OR (source_id = $1 AND oneway = false) LIMIT 5", end_node)
        for r in rows:
            print(f"Edge {r['id']}: Source={r['source_id']}, Target={r['target_id']}, Oneway={r['oneway']}, Type={r['highway_type']}")

        # 4. Raw Dijkstra Check (No BBOX)
        print("\n--- Running Raw Dijkstra (No BBOX) ---")
        query_raw = """
        SELECT * FROM pgr_dijkstra(
            'SELECT id, source_id as source, target_id as target, base_travel_time_sec as cost, 
             CASE WHEN oneway THEN -1.0 ELSE base_travel_time_sec END as reverse_cost 
             FROM graphs.edges',
            $1::bigint, $2::bigint, directed := true
        )
        """
        try:
            path = await conn.fetch(query_raw, int(start_node), int(end_node))
            if path:
                print(f"SUCCESS: Raw Route found! Nodes: {len(path)}")
                cost = sum([r['cost'] for r in path if r['cost']>0])
                print(f"Total Cost: {cost}")
            else:
                print("FAILURE: No route found even without BBOX.")
        except Exception as e:
            print(f"Raw Dijkstra Execution Failed: {e}")

        # 5. BBOX Dijkstra Check (Replicating App Logic)
        print("\n--- Running BBOX Dijkstra (App Logic) ---")
        query_bbox = """
            WITH 
            start_n AS (SELECT geom FROM graphs.nodes WHERE id = $1),
            end_n AS (SELECT geom FROM graphs.nodes WHERE id = $2),
            bbox_coords AS (
                SELECT 
                    ST_XMin(box) as minx,
                    ST_YMin(box) as miny,
                    ST_XMax(box) as maxx,
                    ST_YMax(box) as maxy
                FROM (
                    SELECT ST_Expand(ST_Envelope(ST_MakeLine(start_n.geom, end_n.geom)), 0.1) as box 
                    FROM start_n, end_n
                ) sub
            )
            SELECT * FROM pgr_dijkstra(
                format(
                    'SELECT 
                        id, 
                        source_id as source, 
                        target_id as target, 
                        base_travel_time_sec as cost, 
                        CASE 
                            WHEN oneway THEN -1.0 
                            ELSE base_travel_time_sec 
                        END as reverse_cost 
                    FROM graphs.edges 
                    WHERE geometry && ST_MakeEnvelope(%%s, %%s, %%s, %%s, 4326)',
                    (SELECT minx FROM bbox_coords),
                    (SELECT miny FROM bbox_coords),
                    (SELECT maxx FROM bbox_coords),
                    (SELECT maxy FROM bbox_coords)
                ),
                $1::bigint, $2::bigint, directed := true
            )
        """
        try:
            path_bbox = await conn.fetch(query_bbox, int(start_node), int(end_node))
            if path_bbox:
                 print(f"SUCCESS: BBOX Route found! Nodes: {len(path_bbox)}")
            else:
                 print("FAILURE: BBOX Route NOT found.")
        except Exception as e:
            print(f"BBOX Dijkstra Execution Failed: {e}")

    await conn.close()

async def snap_node(conn, lat, lon):
    query = """
        SELECT 
            e.id, source_id, target_id, highway_type,
            ST_Distance(e.geometry::geography, ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography) as dist,
            ST_LineLocatePoint(e.geometry, ST_SetSRID(ST_MakePoint($2, $1), 4326)) as fraction
        FROM graphs.edges e
        ORDER BY e.geometry <-> ST_SetSRID(ST_MakePoint($2, $1), 4326) ASC
        LIMIT 1
    """
    row = await conn.fetchrow(query, lat, lon)
    if not row:
        print("No edge found nearby.")
        return None
        
    print(f"Snapped to Edge {row['id']} ({row['highway_type']}), dist={row['dist']:.2f}m, fraction={row['fraction']:.2f}")
    
    node = row['source_id'] if row['fraction'] <= 0.5 else row['target_id']
    print(f"Selected Node: {node} ({'Source' if node == row['source_id'] else 'Target'})")
    return node

if __name__ == "__main__":
    asyncio.run(main())
