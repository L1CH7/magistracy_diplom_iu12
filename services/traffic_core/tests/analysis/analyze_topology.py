import asyncio
import asyncpg
import os

# Manual DSN since we are outside the container usually
DSN = "postgresql://postgres:postgres@localhost:5432/nav_mas"

async def main():
    print(f"Connecting to {DSN}...")
    try:
        conn = await asyncpg.connect(DSN)
    except Exception as e:
        print(f"Failed to connect: {e}")
        return
    
    print("\n--- Edge-Based Topology Analysis (with Turn Restrictions) ---")
    
    # Считаем компоненты в EB-графе
    # Узлы - это eb_nodes (направленные сегменты), ребра - eb_edges (маневры)
    query_components = """
        SELECT component, count(*) as size
        FROM pgr_connectedComponents(
            'SELECT id, from_eb_node as source, to_eb_node as target, 1.0 as cost 
             FROM graphs.eb_edges'
        )
        GROUP BY component
        ORDER BY size DESC
        LIMIT 20;
    """
    
    try:
        rows = await conn.fetch(query_components)
        total_eb_nodes = await conn.fetchval("SELECT count(*) FROM graphs.eb_nodes")
        
        if not rows:
             print("No components found in graphs.eb_edges! Did you run the builder?")
             return

        print(f"Total EB-Nodes: {total_eb_nodes}")
        print(f"Components Found: {len(rows)} (top 20 shown)")
        print(f"{'Comp ID':<10} | {'Size':<10} | {'% of Total'}")
        print("-" * 35)
        
        for r in rows:
            pct = (r['size'] / total_eb_nodes) * 100
            print(f"{r['component']:<10} | {r['size']:<10} | {pct:.2f}%")
            
        if len(rows) > 1:
            main_pct = (rows[0]['size'] / total_eb_nodes) * 100
            if main_pct < 100:
                print(f"\n[WARNING] Edge-Based graph is FRAGMENTED!")
                print(f"Main component covers only {main_pct:.2f}% of nodes.")
                print("Turn Restrictions or oneway gaps likely created these fragments.")
            else:
                print("\n[SUCCESS] Edge-Based graph is fully connected.")
        else:
            print("\n[SUCCESS] Edge-Based graph is fully connected (1 component).")

    except Exception as e:
        print(f"Analysis failed: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
