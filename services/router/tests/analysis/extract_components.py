import asyncio
import asyncpg
import csv
from services.common.config import load_settings

async def main():
    settings = load_settings()
    dsn = f"postgresql://{settings.db.user}:{settings.db.password}@{settings.db.host}:{settings.db.port}/{settings.db.name}"
    
    import os
    os.makedirs('/app/benchmarks/router/components', exist_ok=True)
    
    conn = await asyncpg.connect(dsn)
    print("Extracting components...")
    
    # Get component ID for every node
    query = """
        WITH components AS (
            SELECT node, component
            FROM pgr_connectedComponents(
                'SELECT id, source_id as source, target_id as target, 
                 cost, reverse_cost 
                 FROM graphs.edges'
            )
        )
        SELECT n.id, ST_X(n.geom) as lon, ST_Y(n.geom) as lat, c.component
        FROM graphs.nodes n
        JOIN components c ON n.id = c.node
    """
    
    rows = await conn.fetch(query)
    
    with open('/app/benchmarks/router/components/components.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['node_id', 'lon', 'lat', 'component'])
        for r in rows:
            writer.writerow([r['id'], r['lon'], r['lat'], r['component']])
    
    print(f"Exported {len(rows)} nodes to components.csv")

    # 2. Extract Convex Hulls for Islands (for visualization)
    print("Extracting Island Hulls...")
    query_hulls = """
        WITH comp AS (
            SELECT node, component
            FROM pgr_connectedComponents(
                'SELECT id, source_id as source, target_id as target, 
                 cost, reverse_cost 
                 FROM graphs.edges'
            )
        ),
        stats AS (
            SELECT component, count(*) as cnt FROM comp GROUP BY component
        ),
        main_c AS (
            SELECT component FROM stats ORDER BY cnt DESC LIMIT 1
        )
        SELECT c.component, ST_AsText(ST_ConvexHull(ST_Collect(n.geom))) as hull_wkt
        FROM comp c
        JOIN graphs.nodes n ON c.node = n.id
        WHERE c.component != (SELECT component FROM main_c) -- Only Islands
        GROUP BY c.component
    """
    try:
        hull_rows = await conn.fetch(query_hulls)
        with open('/app/benchmarks/router/components/island_hulls.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['component', 'wkt'])
            for r in hull_rows:
                writer.writerow([r['component'], r['hull_wkt']])
        print(f"Exported {len(hull_rows)} island hulls.")
    except Exception as e:
        print(f"Failed to extract hulls: {e}")

    # 3. Extract Main Component Edges (for visualization)
    print("Extracting Main Component Edges...")
    query_edges = """
        WITH comp AS (
            SELECT node, component
            FROM pgr_connectedComponents(
                'SELECT id, source_id as source, target_id as target, 
                 cost, reverse_cost 
                 FROM graphs.edges'
            )
        ),
        stats AS (
            SELECT component, count(*) as cnt FROM comp GROUP BY component
        ),
        main_c AS (
            SELECT component FROM stats ORDER BY cnt DESC LIMIT 1
        )
        SELECT ST_AsText(e.geometry) as wkt
        FROM graphs.edges e
        JOIN comp c ON e.source_id = c.node
        WHERE c.component = (SELECT component FROM main_c)
    """
    try:
        # Use a cursor or fetch in batches if too large, but 400k rows is manageable in memory (~100MB)
        # asyncpg fetch loads all into memory.
        edge_rows = await conn.fetch(query_edges)
        
        with open('/app/benchmarks/router/components/main_edges.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['wkt'])
            for r in edge_rows:
                writer.writerow([r['wkt']])
        print(f"Exported {len(edge_rows)} main component edges.")
    except Exception as e:
        print(f"Failed to extract main edges: {e}")

    # 4. Extract Island Edges (for visualization)
    print("Extracting Island Edges...")
    query_island_edges = """
        WITH comp AS (
            SELECT node, component
            FROM pgr_connectedComponents(
                'SELECT id, source_id as source, target_id as target, 
                 cost, reverse_cost 
                 FROM graphs.edges'
            )
        ),
        stats AS (
            SELECT component, count(*) as cnt FROM comp GROUP BY component
        ),
        main_c AS (
            SELECT component FROM stats ORDER BY cnt DESC LIMIT 1
        )
        SELECT ST_AsText(e.geometry) as wkt
        FROM graphs.edges e
        JOIN comp c ON e.source_id = c.node
        WHERE c.component != (SELECT component FROM main_c)
    """
    try:
        island_rows = await conn.fetch(query_island_edges)
        
        with open('/app/benchmarks/router/components/island_edges.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['wkt'])
            for r in island_rows:
                writer.writerow([r['wkt']])
        print(f"Exported {len(island_rows)} island edges.")
    except Exception as e:
        print(f"Failed to extract island edges: {e}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
