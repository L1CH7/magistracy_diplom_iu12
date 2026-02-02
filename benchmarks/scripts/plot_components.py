import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def main():
    csv_path = "benchmarks/router/components/components.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Run 'make extract-components' first.")
        return

    print(f"Loading {csv_path}...")
    df = pd.read_csv(csv_path)
    
    # Identify largest component
    # Identify largest component
    comp_sizes = df['component'].value_counts()
    main_comp_id = comp_sizes.idxmax()
    
    # Load Island Hulls
    hulls_path = "benchmarks/router/components/island_hulls.csv"
    hulls_map = {}
    import re
    from matplotlib.patches import Polygon as MplPolygon
    from matplotlib.collections import PatchCollection

    if os.path.exists(hulls_path):
        print(f"Loading {hulls_path}...")
        hf = pd.read_csv(hulls_path)
        for _, row in hf.iterrows():
            wkt = row['wkt']
            cid = row['component']
            # Simple WKT parser for POLYGON/POINT/LINESTRING
            # We expect POLYGON((x y, x y ...)) or POINT(x y)
            coords = []
            if 'POLYGON' in wkt:
                # Extract content inside ((...))
                content = re.search(r'\(\((.*?)\)\)', wkt)
                if content:
                    pairs = content.group(1).split(',')
                    for p in pairs:
                        parts = p.strip().split()
                        coords.append((float(parts[0]), float(parts[1])))
                hulls_map[cid] = coords
            elif 'POINT' in wkt:
                 # Single point "hull"
                 pass # Already covered by scatter plot if included, or we can add a small circle?
    
    plt.figure(figsize=(24, 24), dpi=400) # Ultra High Resolution
    ax = plt.gca()
    ax.set_facecolor('white')
    
    # 1. Plot Main Component (Lines)
    edges_path = "benchmarks/router/components/main_edges.csv"
    from matplotlib.collections import LineCollection
    import re
    
    if os.path.exists(edges_path):
        print(f"Loading {edges_path}...")
        ef = pd.read_csv(edges_path)
        segments = []
        for _, row in ef.iterrows():
            wkt = row['wkt']
            if 'LINESTRING' in wkt:
                content = re.search(r'\((.*?)\)', wkt)
                if content:
                    pairs = content.group(1).split(',')
                    pts = []
                    for p in pairs:
                         parts = p.strip().split()
                         pts.append((float(parts[0]), float(parts[1])))
                    segments.append(pts)
        
        print(f"Plotting {len(segments)} main component edges...")
        lc = LineCollection(segments, colors='black', linewidths=0.3, alpha=0.5, label='Main Network')
        ax.add_collection(lc)
    else:
        print("Main edges not found, using scatter fallback.")
        main = df[df['component'] == main_comp_id]
        plt.scatter(main['lon'], main['lat'], c='black', s=0.05, alpha=0.6, label='Main Network (Nodes)')
    
    # 2. Plot Island Edges (Red, Thicker, On Top)
    island_edges_path = "benchmarks/router/components/island_edges.csv"
    
    if os.path.exists(island_edges_path):
        print(f"Loading {island_edges_path}...")
        ief = pd.read_csv(island_edges_path)
        isegments = []
        for _, row in ief.iterrows():
            wkt = row['wkt']
            if 'LINESTRING' in wkt:
                content = re.search(r'\((.*?)\)', wkt)
                if content:
                    pairs = content.group(1).split(',')
                    pts = []
                    for p in pairs:
                         parts = p.strip().split()
                         pts.append((float(parts[0]), float(parts[1])))
                    isegments.append(pts)
        
        print(f"Plotting {len(isegments)} island edges...")
        ilc = LineCollection(isegments, colors='red', linewidths=.5, alpha=1.0, label='Islands (Disconnected)')
        ax.add_collection(ilc)
    
    plt.title(f"Graph Connectivity Map\nMain: {comp_sizes[main_comp_id]:,} nodes | Islands: {len(comp_sizes)-1} components", fontsize=22)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    
    # Custom Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='black', lw=1, label='Main Network'),
        Line2D([0], [0], color='red', lw=2, label='Islands (Disconnected)'),
    ]
    plt.legend(handles=legend_elements, loc='upper right', fontsize=14)
    
    plt.grid(True, alpha=0.1)
    plt.axis('equal')
    
    output_path = "benchmarks/router/plots/components_map.png"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, bbox_inches='tight')
    print(f"Saved map to {output_path}")

if __name__ == "__main__":
    main()
