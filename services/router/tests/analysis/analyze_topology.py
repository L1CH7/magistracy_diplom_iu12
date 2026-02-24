import asyncio
import asyncpg
from services.common.config import load_settings

async def main():
    settings = load_settings()
    dsn = f"postgresql://{settings.db.user}:{settings.db.password}@{settings.db.host}:{settings.db.port}/{settings.db.name}"
    
    print(f"Connecting to {dsn}...")
    conn = await asyncpg.connect(dsn)
    
    print("Analyzing Connected Components (this might take a moment)...")
    
    # 1. Get Component Distribution
    query_components = """
        SELECT component, count(*) as size
        FROM pgr_connectedComponents(
            'SELECT id, source_id as source, target_id as target, 
             cost, reverse_cost 
             FROM graphs.edges'
        )
        GROUP BY component
        ORDER BY size DESC
    """
    
    output_lines = []
    def log(msg):
        print(msg)
        output_lines.append(str(msg))

    try:
        rows = await conn.fetch(query_components)
        
        total_nodes = sum(r['size'] for r in rows)
        if not rows:
             log("No components found!")
             return

        main_component = rows[0]
        islands = rows[1:]
        
        log(f"\nTotal Nodes Processed: {total_nodes}")
        log(f"Components Found: {len(rows)}")
        log(f"Main Component Size: {main_component['size']} ({main_component['size']/total_nodes*100:.2f}%)")
        log(f"Number of Isolated Islands: {len(islands)}")
        
        if islands:
            log("\n--- Top 10 Largest Islands ---")
            for i, r in enumerate(islands[:10]):
                log(f"Island {r['component']}: {r['size']} nodes")
                
            # 2. Get Details for a specific Island
            target_component = islands[0]['component']
            log(f"\n--- Coordinates for Island {target_component} (Size: {islands[0]['size']}) ---")
            
            # Join with nodes table to get geometry
            query_island_nodes = """
                WITH comp AS (
                    SELECT node 
                    FROM pgr_connectedComponents(
                        'SELECT id, source_id as source, target_id as target, 
                         cost, reverse_cost 
                         FROM graphs.edges'
                    )
                    WHERE component = $1
                )
                SELECT n.id, ST_Y(n.geom) as lat, ST_X(n.geom) as lon
                FROM graphs.nodes n
                JOIN comp c ON n.id = c.node
                LIMIT 5
            """
            
            island_nodes = await conn.fetch(query_island_nodes, target_component)
            for node in island_nodes:
                log(f"Node {node['id']}: {node['lat']}, {node['lon']}")

        # Write to file
        import os
        os.makedirs('/app/benchmarks/router/components', exist_ok=True)
        with open('/app/benchmarks/router/components/topology_report.txt', 'w') as f:
            f.write('\n'.join(output_lines))
        print("\nReport saved to benchmarks/router/components/topology_report.txt")
                
    except Exception as e:
        print(f"Analysis failed: {e}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
