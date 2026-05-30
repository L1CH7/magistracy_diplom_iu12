import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set premium academic styles
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
    Groups by RouteID and bins complexity based on the physical path length of the route.
    Calculates the exact average kilometer distance for each bucket to use as numerical x-axis ticks.
    """
    route_lengths = df.groupby('RouteID')['PathLengthM'].mean().reset_index()
    route_lengths['Bucket'] = pd.qcut(route_lengths['PathLengthM'], q=20, labels=list(range(20)))
    
    bucket_means = route_lengths.groupby('Bucket', observed=False)['PathLengthM'].mean() / 1000.0
    
    route_to_bucket = dict(zip(route_lengths['RouteID'], route_lengths['Bucket']))
    df['Bucket'] = df['RouteID'].map(route_to_bucket)
    df['PathLengthKm'] = df['Bucket'].map(bucket_means)
    
    return df, sorted(list(bucket_means.values))

def plot_metric_vs_complexity(df, x_values, metric_col, y_label, title, save_path, log_scale=True, formula_lambda=None):
    """
    Plots a multi-axis premium line chart for a specific metric vs route physical complexity.
    """
    df_copy = df.copy()
    if formula_lambda:
        df_copy[metric_col] = formula_lambda(df_copy)
        
    agg = df_copy.groupby(['Algorithm', 'Queue', 'PathLengthKm'], observed=False)[metric_col].mean().reset_index()
    
    algorithms = agg['Algorithm'].unique()
    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    axes = axes.flatten()
    
    for idx, algo in enumerate(algorithms):
        ax = axes[idx]
        algo_data = agg[agg['Algorithm'] == algo]
        
        for queue_name in COLORS.keys():
            queue_data = algo_data[algo_data['Queue'] == queue_name]
            if queue_data.empty:
                continue
                
            queue_data = queue_data.set_index('PathLengthKm').reindex(x_values).reset_index()
            x_labels = [f"{v:.2f}" for v in queue_data['PathLengthKm']]
            
            ax.plot(
                x_labels,
                queue_data[metric_col],
                label=queue_name,
                color=COLORS[queue_name],
                linestyle=LINE_STYLES[queue_name],
                marker=MARKERS[queue_name],
                markersize=8,
                linewidth=2.5 if queue_name == '8-ary' else 1.5,
                alpha=0.95
            )
            
        ax.set_title(f"Algorithm: {algo}", fontweight='bold', pad=10)
        ax.tick_params(axis='x', rotation=45)
        if log_scale:
            ax.set_yscale('log')
            ax.set_ylabel(f"{y_label} (Log Scale)" if idx % 2 == 0 else "")
        else:
            ax.set_ylabel(y_label if idx % 2 == 0 else "")
            
        ax.set_xlabel("Mean Path Length (Kilometers)" if idx >= 2 else "")
        ax.grid(True, which="both", linestyle='--', alpha=0.5)
        
        if idx == 0:
            ax.legend(title="Queue Types", frameon=True, shadow=False, facecolor='white', edgecolor='#e0e0e0')
            
    plt.suptitle(title, fontweight='bold', y=0.98, fontsize=16)
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Line plot saved to: {save_path}")

def plot_best_combinations(df, x_values, save_path):
    """
    Plots the ultimate showdown between the best combinations on a single premium line chart.
    """
    df_copy = df.copy()
    df_copy['QPS'] = 1000.0 / df_copy['TimeMs']
    
    best_combos = [
        ('Dijkstra', '8-ary'),
        ('Dijkstra', 'radix'),
        ('Bi-Dijkstra', '8-ary'),
        ('Bi-Dijkstra', 'radix'),
        ('A-Star', '8-ary'),
        ('A-Star', 'radix'),
        ('ALT', '8-ary'),
        ('ALT', 'radix')
    ]
    
    df_copy['Combo'] = df_copy['Algorithm'] + " + " + df_copy['Queue']
    combo_names = [f"{algo} + {queue}" for algo, queue in best_combos]
    df_copy = df_copy[df_copy['Combo'].isin(combo_names)]
    
    agg = df_copy.groupby(['Combo', 'PathLengthKm'], observed=False)['QPS'].mean().reset_index()
    
    plt.figure(figsize=(12, 8))
    
    combo_colors = {
        'Dijkstra + 8-ary': '#4A90E2',      # Soft Blue
        'Dijkstra + radix': '#9013FE',      # Purple
        'Bi-Dijkstra + 8-ary': '#D0021B',   # Vibrant Red (Best of Bi-Dijkstra)
        'Bi-Dijkstra + radix': '#BD10E0',   # Pink/Magenta
        'A-Star + 8-ary': '#F5A623',        # Orange
        'A-Star + radix': '#FFD300',        # Yellow
        'ALT + 8-ary': '#7ED321',           # Green (Best of ALT)
        'ALT + radix': '#50E3C2'            # Mint/Teal
    }
    
    combo_markers = {
        'Dijkstra + 8-ary': 'o',
        'Dijkstra + radix': 's',
        'Bi-Dijkstra + 8-ary': '^',
        'Bi-Dijkstra + radix': 'D',
        'A-Star + 8-ary': 'p',
        'A-Star + radix': '*',
        'ALT + 8-ary': 'v',
        'ALT + radix': 'h'
    }
    
    for combo in combo_names:
        combo_data = agg[agg['Combo'] == combo]
        if combo_data.empty:
            continue
            
        combo_data = combo_data.set_index('PathLengthKm').reindex(x_values).reset_index()
        x_labels = [f"{v:.2f}" for v in combo_data['PathLengthKm']]
        
        plt.plot(
            x_labels,
            combo_data['QPS'],
            label=combo,
            color=combo_colors.get(combo, '#000000'),
            marker=combo_markers.get(combo, 'o'),
            markersize=9,
            linewidth=2.5 if '8-ary' in combo else 1.8,
            alpha=0.95
        )
        
    plt.title("Ultimate Routing Algorithms & Queues Showdown (QPS vs Distance)", fontweight='bold', pad=15, fontsize=14)
    plt.yscale('log')
    plt.ylabel("Average QPS (Queries/sec, Log Scale)", fontsize=12)
    plt.xlabel("Mean Path Length (Kilometers)", fontsize=12)
    plt.xticks(rotation=45)
    plt.grid(True, which="both", linestyle='--', alpha=0.5)
    plt.legend(title="Algorithm & Queue Combo", frameon=True, facecolor='white', edgecolor='#e0e0e0', loc='lower left')
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Ultimate showdown line plot saved to: {save_path}")

def plot_queue_overhead_trend(df, x_values, save_path):
    """
    Plots the percentage of total time spent inside the queue as a trend vs physical distance.
    Uses Seaborn's lineplot to automatically calculate and show the dispersion (confidence interval / variance band).
    """
    df_copy = df.copy()
    df_copy['QueueOverheadPct'] = (df_copy['QueueTimeMs'] / df_copy['TimeMs']) * 100.0
    df_copy['QueueOverheadPct'] = df_copy['QueueOverheadPct'].clip(0, 100)
    
    # We round PathLengthKm to 2 decimals for plotting
    df_copy['PathLengthKm_Rounded'] = df_copy['PathLengthKm'].round(2)
    
    plt.figure(figsize=(12, 8))
    
    # Use seaborn lineplot to draw lines + variance band (shaded area of standard error/deviation)
    sns.lineplot(
        data=df_copy,
        x='PathLengthKm_Rounded',
        y='QueueOverheadPct',
        hue='Queue',
        palette=COLORS,
        style='Queue',
        markers=MARKERS,
        dashes=LINE_STYLES,
        markersize=8,
        err_style="band",   # Renders the variance band
        errorbar=("ci", 95), # 95% confidence interval shows the variance nicely
        linewidth=2.0
    )
    
    plt.title("Queue Overhead Trend vs Route Distance (with 95% Variance Band)", fontweight='bold', pad=15, fontsize=14)
    plt.ylabel("Time spent in Queue Operations (%)", fontsize=12)
    plt.xlabel("Route Physical Length (Kilometers)", fontsize=12)
    plt.xticks(rotation=45)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(title="Queue Types", frameon=True, facecolor='white', edgecolor='#e0e0e0')
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Queue overhead trend with variance saved to: {save_path}")

def plot_hardware_cycles_comparison(df, save_path):
    """
    Plots direct, raw hardware performance of queues: Average CPU cycles spent per push and pop.
    This is an absolute hardware metric, independent of graph topography.
    """
    # Group globally by Queue
    agg = df.groupby('Queue')[['AvgPushCycles', 'AvgPopCycles']].mean().reset_index()
    
    # Transform to long format for Seaborn bar plotting
    melted = pd.melt(agg, id_vars=['Queue'], value_vars=['AvgPushCycles', 'AvgPopCycles'],
                     var_name='Operation', value_name='CpuCycles')
    
    melted['Operation'] = melted['Operation'].map({'AvgPushCycles': 'Push Operation', 'AvgPopCycles': 'Pop Operation'})
    
    plt.figure(figsize=(12, 7))
    sns.barplot(
        data=melted,
        x='Queue',
        y='CpuCycles',
        hue='Operation',
        palette={'Push Operation': '#4A90E2', 'Pop Operation': '#D0021B'},
        edgecolor='black',
        linewidth=1.0
    )
    
    plt.title("Hardware Performance: Precise CPU Cycles per Operation (lfence serialized)", fontweight='bold', pad=15, fontsize=14)
    plt.ylabel("Average CPU Cycles (Lower is Faster)", fontsize=12)
    plt.xlabel("Queue Type", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Hardware CPU cycles bar plot saved to: {save_path}")

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
    df, x_values = apply_request_based_binning(df)
    
    # 2. Plot QPS vs Route Complexity
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='QPS',
        y_label='Average QPS (Queries/sec)',
        title='Routing Performance (QPS) vs Route Distance',
        save_path=os.path.join(results_dir, 'qps_comparison.png'),
        log_scale=True,
        formula_lambda=lambda x: 1000.0 / x['TimeMs']
    )
    
    # 3. Plot Visited Nodes (Количество раскрытых узлов)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='VisitedNodes',
        y_label='Average Visited Nodes count',
        title='Search Space Complexity (Visited Nodes) vs Route Distance',
        save_path=os.path.join(results_dir, 'visited_nodes_comparison.png'),
        log_scale=True
    )
    
    # 4. Plot Iteration Time (Время одной итерации / раскрытия в наносекундах)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='IterationTimeNs',
        y_label='Average Step Duration (Nanoseconds)',
        title='Single Node Processing Cost (Iteration Duration) vs Route Distance',
        save_path=os.path.join(results_dir, 'iteration_time_comparison.png'),
        log_scale=True,
        formula_lambda=lambda x: (x['TimeMs'] * 1e6) / x['VisitedNodes'].replace(0, 1)
    )
    
    # 5. Plot Queue Operations Count (Количество push+pop операций)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='QueueOps',
        y_label='Queue Operations (Push + Pop Count)',
        title='Queue Workload (Total Push & Pop Operations) vs Route Distance',
        save_path=os.path.join(results_dir, 'queue_operations_comparison.png'),
        log_scale=True,
        formula_lambda=lambda x: x['PushCount'] + x['PopCount']
    )
    
    # 6. Ultimate Showdown of best combinations
    plot_best_combinations(df, x_values, os.path.join(results_dir, 'best_combinations_comparison.png'))
    
    # 7. Queue overhead trend with 95% variance band
    plot_queue_overhead_trend(df, x_values, os.path.join(results_dir, 'queue_overhead_trend.png'))
    
    # 8. Direct Hardware CPU Cycles comparison (Push vs Pop)
    plot_hardware_cycles_comparison(df, os.path.join(results_dir, 'push_pop_cycles_comparison.png'))
    
    print("\n🎉 Analysis completed! All premium scientific charts have been saved to benchmarks/traffic-core/results/\n")

if __name__ == "__main__":
    main()
