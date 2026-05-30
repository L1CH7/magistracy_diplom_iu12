import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set premium aesthetic styles
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_theme(style="ticks")
plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 14,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'figure.titlesize': 16,
    'figure.dpi': 150
})

# Sleek premium colors for line plotting
COLORS = {
    '2-ary': '#4A90E2',        # Soft Blue
    '4-ary': '#50E3C2',        # Mint/Teal
    '8-ary': '#D0021B',        # Vibrant Red (Our Ultimate Solution)
    '16-ary': '#F5A623',       # Warm Orange
    'sbbh': '#BD10E0',         # Purple
    'bucket': '#9013FE',       # Indigo
    'radix': '#7ED321'         # Green
}

LINE_STYLES = {
    '2-ary': '--',
    '4-ary': '-.',
    '8-ary': '-',
    '16-ary': ':',
    'sbbh': '--',
    'bucket': '-.',
    'radix': '-'
}

MARKERS = {
    '2-ary': 'o',
    '4-ary': 's',
    '8-ary': '^',
    '16-ary': 'D',
    'sbbh': 'x',
    'bucket': '*',
    'radix': 'p'
}

def load_data(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"CSV data file not found at: {filepath}")
    df = pd.read_csv(filepath)
    df = df[df['Crashed'] == 0].copy()
    return df

def apply_request_based_binning(df):
    """
    Groups by RouteID and bins complexity based on the physical path length of the route itself.
    Ensures 100% consistent, equal sample distribution for ALL algorithms and queues
    across exactly the same 4 complexity tiers (Short, Medium, Long, Epic).
    """
    # Extract unique routes and their physical lengths
    route_lengths = df.groupby('RouteID')['PathLengthM'].mean().reset_index()
    
    # Bin them into 4 categories
    labels = ['Short', 'Medium', 'Long', 'Epic']
    route_lengths['Tier'] = pd.qcut(route_lengths['PathLengthM'], q=4, labels=labels, duplicates='drop')
    
    # Merge back to primary dataframe
    tier_mapping = dict(zip(route_lengths['RouteID'], route_lengths['Tier']))
    df['Tier'] = df['RouteID'].map(tier_mapping)
    return df

def plot_qps_by_axis(df, title, save_path):
    """
    Generates QPS comparison chart as a LINE PLOT with LOGARITHMIC scale.
    """
    # Calculate QPS
    df['QPS'] = 1000.0 / df['TimeMs']
    
    # Aggregate to get average QPS for each Algorithm + Queue + Complexity Tier
    agg = df.groupby(['Algorithm', 'Queue', 'Tier'], observed=False)['QPS'].mean().reset_index()
    
    algorithms = agg['Algorithm'].unique()
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    axes = axes.flatten()
    
    tiers = ['Short', 'Medium', 'Long', 'Epic']
    
    for idx, algo in enumerate(algorithms):
        ax = axes[idx]
        algo_data = agg[agg['Algorithm'] == algo]
        
        # Plot each queue as a line
        for queue_name in COLORS.keys():
            queue_data = algo_data[algo_data['Queue'] == queue_name]
            if queue_data.empty:
                continue
                
            # Align by standard order of tiers
            queue_data = queue_data.set_index('Tier').reindex(tiers).reset_index()
            
            ax.plot(
                queue_data['Tier'],
                queue_data['QPS'],
                label=queue_name,
                color=COLORS[queue_name],
                linestyle=LINE_STYLES[queue_name],
                marker=MARKERS[queue_name],
                markersize=8,
                linewidth=2.0 if queue_name == '8-ary' else 1.5,
                alpha=0.9
            )
            
        ax.set_title(f"Algorithm: {algo}", fontweight='bold', pad=10)
        ax.set_yscale('log')  # Logarithmic scale for beautiful multi-magnitude comparison
        ax.set_ylabel("Average QPS (Queries/sec, Log Scale)" if idx % 2 == 0 else "")
        ax.set_xlabel("Route Physical Complexity Tier" if idx >= 2 else "")
        ax.grid(True, which="both", linestyle='--', alpha=0.5)
        
        # Style legend
        if idx == 0:
            ax.legend(title="Queue Types", frameon=True, shadow=False, facecolor='white', edgecolor='#e0e0e0')
            
    plt.suptitle(f"Routing Performance (QPS) comparison by {title} (Log Scale)", fontweight='bold', y=0.98, fontsize=16)
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Line plot saved to: {save_path}")

def plot_queue_overhead(df, save_path):
    """
    Analyzes pure queue overhead as a percentage of overall execution time.
    """
    df['QueueOverheadPct'] = (df['QueueTimeMs'] / df['TimeMs']) * 100.0
    df['QueueOverheadPct'] = df['QueueOverheadPct'].clip(0, 100)
    
    # Aggregate globally per Queue
    agg = df.groupby(['Queue'])['QueueOverheadPct'].mean().reset_index()
    agg = agg.sort_values(by='QueueOverheadPct', ascending=True)
    
    plt.figure(figsize=(10, 6))
    sns.barplot(
        data=agg,
        x='Queue',
        y='QueueOverheadPct',
        palette=COLORS,
        edgecolor='black',
        linewidth=1.0
    )
    
    plt.title("Pure Queue Operations Overhead (% of total routing time)", fontweight='bold', pad=15)
    plt.xlabel("Priority Queue Type")
    plt.ylabel("Time Spent in Queue Operations (%)")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Overhead bar plot saved to: {save_path}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.abspath(os.path.join(script_dir, "..", "stats", "run_results.csv"))
    results_dir = os.path.abspath(os.path.join(script_dir, "..", "results"))
    
    print("📈 Analyzing benchmark results with rigorous scientific methodology...")
    try:
        df = load_data(csv_path)
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return
        
    os.makedirs(results_dir, exist_ok=True)
    
    # 1. Apply request-based binning to ensure 100% clean and consistent graphs
    df = apply_request_based_binning(df)
    
    # 2. Plot line graph of QPS vs Route Complexity
    plot_qps_by_axis(
        df, 
        'Route Path Length Complexity', 
        os.path.join(results_dir, 'qps_by_route_complexity.png')
    )
    
    # 3. Queue overhead analysis
    plot_queue_overhead(df, os.path.join(results_dir, 'queue_overhead_percentage.png'))
    
    print("\n🎉 Analysis completed! Premium line charts have been saved to benchmarks/traffic-core/results/\n")

if __name__ == "__main__":
    main()
