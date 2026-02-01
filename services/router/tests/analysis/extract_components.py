import asyncio
import asyncpg
import csv
from services.common.config import load_settings

async def main():
    settings = load_settings()
    dsn = f"postgresql://{settings.db.user}:{settings.db.password}@{settings.db.host}:{settings.db.port}/{settings.db.name}"
    
    conn = await asyncpg.connect(dsn)
    print("Extracting components...")
    
    # Get component ID for every node
    query = """
        WITH components AS (
            SELECT node, component
            FROM pgr_connectedComponents(
                'SELECT id, source_id as source, target_id as target, 
                 base_travel_time_sec as cost, base_travel_time_sec as reverse_cost 
                 FROM graphs.edges'
            )
        )
        SELECT n.id, ST_X(n.geom) as lon, ST_Y(n.geom) as lat, c.component
        FROM graphs.nodes n
        JOIN components c ON n.id = c.node
    """
    
    rows = await conn.fetch(query)
    
    with open('/app/benchmarks/components.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['node_id', 'lon', 'lat', 'component'])
        for r in rows:
            writer.writerow([r['id'], r['lon'], r['lat'], r['component']])
            
    print(f"Exported {len(rows)} nodes to components.csv")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
