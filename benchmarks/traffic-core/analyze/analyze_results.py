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
    'delta': '#BD10E0',        # Purple
    'bucket': '#9013FE',       # Indigo
    'radix': '#7ED321'         # Green
}

LINE_STYLES = {
    '2-ary': '--',
    '4-ary': '-.',
    '8-ary': '-',
    '16-ary': ':',
    'delta': '--',
    'bucket': '-.',
    'radix': '-'
}

MARKERS = {
    '2-ary': 'o',
    '4-ary': 's',
    '8-ary': '^',
    '16-ary': 'D',
    'delta': 'X',
    'bucket': '*',
    'radix': 'p'
}

def load_data(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"CSV data file not found at: {filepath}")
    df = pd.read_csv(filepath)
    df = df[df['Crashed'] == 0].copy()
    if 'PathEdges' not in df.columns:
        df['PathEdges'] = 0
    return df

def apply_request_based_binning(df):
    """
    Groups by RouteID and bins complexity based on the path edges count (PathEdges).
    Calculates the exact average edge count for each bucket to use as numerical x-axis ticks.
    """
    route_edges = df.groupby('RouteID')['PathEdges'].mean().reset_index()
    # Safe qcut for case when there are not enough unique values (e.g. filled with zeros)
    try:
        route_edges['Bucket'] = pd.qcut(route_edges['PathEdges'], q=10, labels=False, duplicates='drop')
    except ValueError:
        route_edges['Bucket'] = 0
        
    bucket_means = route_edges.groupby('Bucket', observed=False)['PathEdges'].mean().round().astype(int)
    
    route_to_bucket = dict(zip(route_edges['RouteID'], route_edges['Bucket']))
    df['Bucket'] = df['RouteID'].map(route_to_bucket)
    df['PathEdgesAvg'] = df['Bucket'].map(bucket_means)
    
    return df, sorted(list(bucket_means.values))

def plot_metric_vs_complexity(df, x_values, metric_col, y_label, title, save_path, log_scale=True, formula_lambda=None):
    """
    Plots a multi-axis premium line chart for a specific metric vs route physical complexity.
    """
    df_copy = df.copy()
    if metric_col == 'QPS':
        agg = df_copy.groupby(['Algorithm', 'Queue', 'PathEdgesAvg'], observed=False)['TimeMs'].mean().reset_index()
        agg['QPS'] = 1000.0 / agg['TimeMs']
    else:
        if formula_lambda:
            df_copy[metric_col] = formula_lambda(df_copy)
        agg = df_copy.groupby(['Algorithm', 'Queue', 'PathEdgesAvg'], observed=False)[metric_col].mean().reset_index()
    
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
                
            queue_data = queue_data.set_index('PathEdgesAvg').reindex(x_values).reset_index()
            
            ax.plot(
                queue_data['PathEdgesAvg'],
                queue_data[metric_col],
                label=queue_name,
                color=COLORS[queue_name],
                linestyle=LINE_STYLES[queue_name],
                linewidth=2.5 if queue_name == '8-ary' else 1.5,
                alpha=0.95
            )
            
        ax.set_title(f"Алгоритм: {algo}", fontweight='bold', pad=10)
        if log_scale:
            ax.set_yscale('log')
            ax.set_ylabel(f"{y_label} (Лог. масштаб)" if idx % 2 == 0 else "")
        else:
            ax.set_ylabel(y_label if idx % 2 == 0 else "")
            
        ax.set_xlabel("Сложность маршрута (число ребер пути)" if idx >= 2 else "")
        ax.grid(True, which="both", linestyle='--', alpha=0.5)
        
        if idx == 0:
            ax.legend(title="Типы очередей", frameon=True, shadow=False, facecolor='white', edgecolor='#e0e0e0')
            
    plt.suptitle(title, fontweight='bold', y=0.98, fontsize=16)
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Line plot saved to: {save_path}")

def plot_best_combinations(df, x_values, save_path):
    """
    Plots the ultimate showdown between the dynamically selected best combinations on a single premium line chart.
    """
    df_copy = df.copy()
    
    # Dynamically select TOP-2 queues (TOP-3 for ALT) for each algorithm based on mean execution time
    best_combos = []
    for algo in df_copy['Algorithm'].unique():
        algo_df = df_copy[df_copy['Algorithm'] == algo]
        mean_time = algo_df.groupby('Queue')['TimeMs'].mean().sort_values(ascending=True) # Less time is better
        n_top = 3 if algo == 'ALT' else 2
        top_queues = mean_time.index[:n_top].tolist()
        for q in top_queues:
            best_combos.append((algo, q))
            
    print("  [Динамический отбор лучших комбинаций по QPS]:", best_combos)
    
    combo_names = [f"{algo} + {queue}" for algo, queue in best_combos]
    df_copy = df_copy[(df_copy['Algorithm'].astype(str) + " + " + df_copy['Queue'].astype(str)).isin(combo_names)].copy()
    
    # Aggregate by mean TimeMs to compute true mathematical QPS for each bucket
    agg = df_copy.groupby(['Algorithm', 'Queue', 'PathEdgesAvg'], observed=False)['TimeMs'].mean().reset_index()
    agg['QPS'] = 1000.0 / agg['TimeMs']
    agg['Combo'] = agg['Algorithm'].astype(str) + " + " + agg['Queue'].astype(str)
    
    plt.figure(figsize=(13.5, 8)) # Slightly wider figure to accommodate legend on the right
    
    # Dynamic palette to render multiple lines elegantly
    distinct_colors = ['#4A90E2', '#50E3C2', '#D0021B', '#F5A623', '#BD10E0', '#7ED321', '#9013FE', '#FF5A5F', '#54B435', '#222831']
    distinct_markers = ['o', 's', '^', 'D', 'p', '*', 'v', 'h', 'P', 'X']
    
    combo_colors = {}
    combo_markers = {}
    for idx, combo in enumerate(combo_names):
        combo_colors[combo] = distinct_colors[idx % len(distinct_colors)]
        combo_markers[combo] = distinct_markers[idx % len(distinct_markers)]
        
    lines = []
    for combo in combo_names:
        combo_data = agg[agg['Combo'] == combo]
        if combo_data.empty:
            continue
            
        combo_data = combo_data.set_index('PathEdgesAvg').reindex(x_values).reset_index()
        
        # Determine last valid QPS point for legend sorting
        valid_qps = combo_data['QPS'].dropna()
        last_qps = valid_qps.iloc[-1] if not valid_qps.empty else 0.0
        
        line, = plt.plot(
            combo_data['PathEdgesAvg'],
            combo_data['QPS'],
            color=combo_colors.get(combo, '#000000'),
            linewidth=2.5 if '8-ary' in combo else 1.8,
            alpha=0.95
        )
        lines.append((last_qps, line, combo))
        
    # Sort legend items by QPS descending (highest line first)
    lines.sort(key=lambda x: x[0], reverse=True)
    handles = [item[1] for item in lines]
    labels = [item[2] for item in lines]
        
    plt.title("Сравнение лучших комбинаций алгоритмов и очередей (QPS)", fontweight='bold', pad=15, fontsize=14)
    plt.yscale('log')
    plt.ylabel("Средняя производительность QPS (запросов/сек, лог. масштаб)", fontsize=12)
    plt.xlabel("Сложность маршрута (число ребер пути)", fontsize=12)
    plt.grid(True, which="both", linestyle='--', alpha=0.5)
    
    # Legend sorted by QPS, reduced font sizes, placed to the right
    plt.legend(
        handles,
        labels,
        title="Лучшие комбинации\n(Алгоритм + Очередь)",
        title_fontsize=9,
        fontsize=8.5,
        frameon=True,
        facecolor='white',
        edgecolor='#e0e0e0',
        loc='upper left',
        bbox_to_anchor=(1.01, 1.0)
    )
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Ultimate showdown line plot saved to: {save_path}")

def plot_queue_overhead_trend(df, x_values, save_path):
    """
    Plots the percentage of total execution time spent strictly inside Priority Queue operations.
    Renders a premium sorted Bar Plot sorted by average overhead (descending order).
    """
    df_copy = df.copy()
    df_copy['QueueOverheadPct'] = (df_copy['QueueTimeMs'] / df_copy['TimeMs']) * 100.0
    df_copy['QueueOverheadPct'] = df_copy['QueueOverheadPct'].clip(0, 100)
    
    # Calculate average overhead for each Queue type
    agg = df_copy.groupby('Queue', observed=False)['QueueOverheadPct'].mean().reset_index()
    agg = agg.sort_values(by='QueueOverheadPct', ascending=False) # Order descending (worst to best)
    
    plt.figure(figsize=(11, 7))
    
    # Solid premium blue color #4A90E2 with black edges like in push/pop
    bars = plt.bar(
        agg['Queue'],
        agg['QueueOverheadPct'],
        color='#4A90E2',
        edgecolor='black',
        linewidth=1.0,
        width=0.6
    )
    
    # Add exact values on top of bars
    for bar in bars:
        height = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width()/2.0,
            height + 0.5,
            f"{height:.1f}%",
            ha='center',
            va='bottom',
            fontweight='bold',
            fontsize=10,
            color='#333333'
        )
        
    plt.title("Доля времени на операции с очередью приоритетов (меньше — лучше)", fontweight='bold', pad=15, fontsize=13)
    plt.ylabel("Доля времени выполнения (%)", fontsize=11)
    plt.xlabel("Тип очереди приоритетов", fontsize=11)
    plt.ylim(0, max(agg['QueueOverheadPct']) + 12)
    plt.grid(True, axis='y', linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Queue overhead bar plot saved to: {save_path}")

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
    
    melted['Operation'] = melted['Operation'].map({'AvgPushCycles': 'Операция Push (вставка)', 'AvgPopCycles': 'Операция Pop (извлечение)'})
    
    plt.figure(figsize=(12, 7))
    sns.barplot(
        data=melted,
        x='Queue',
        y='CpuCycles',
        hue='Operation',
        palette={'Операция Push (вставка)': '#4A90E2', 'Операция Pop (извлечение)': '#D0021B'},
        edgecolor='black',
        linewidth=1.0
    )
    
    plt.title("Аппаратная сложность: среднее число тактов CPU на операцию с очередью (lfence сериализация)", fontweight='bold', pad=15, fontsize=14)
    plt.ylabel("Среднее число тактов CPU (меньше — лучше)", fontsize=12)
    plt.xlabel("Тип очереди приоритетов", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(title="Аппаратные операции", frameon=True, facecolor='white', edgecolor='#e0e0e0')
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Hardware CPU cycles bar plot saved to: {save_path}")

def plot_multithreading_scalability(csv_path, save_path):
    """
    Plots absolute RPS throughput vs Thread Count.
    Includes SMT comparison and the Ideal Linear reference limit.
    """
    if not os.path.exists(csv_path):
        print(f"  [Skip] Multithreading CSV not found at: {csv_path}")
        return
        
    df = pd.read_csv(csv_path)
    if df.empty:
        return
        
    # Исключаем физические ядра по запросу пользователя
    df = df[df['Mode'] != 'No-SMT-Affinity'].copy()
        
    plt.figure(figsize=(10, 6))
    
    # Extract baseline RPS for 1 thread (use SMT-Affinity 1 thread)
    baseline_rps_row = df[(df['Mode'] == 'SMT-Affinity') & (df['ThreadCount'] == 1)]
    if baseline_rps_row.empty:
        baseline_rps_row = df[df['ThreadCount'] == 1]
    
    baseline_rps = baseline_rps_row['RPS'].iloc[0] if not baseline_rps_row.empty else 600.0
    
    # Plot Ideal Linear throughput limit
    thread_counts = sorted(df['ThreadCount'].unique())
    ideal_rps_vals = [t * baseline_rps for t in thread_counts]
    plt.plot(
        thread_counts,
        ideal_rps_vals,
        linestyle='--',
        color='#9B9B9B',
        linewidth=2,
        label="Теоретический предел"
    )
    
    colors_map = {
        'No-Affinity': '#4A90E2',      # Soft Blue
        'SMT-Affinity': '#D0021B',     # Vibrant Red (SMT / Hyper-Threading)
    }
    
    markers_map = {
        'No-Affinity': 'o',
        'SMT-Affinity': '^',
    }
    
    mode_labels = {
        'No-Affinity': 'Без привязки (планировщик ОС)',
        'SMT-Affinity': 'С привязкой к ядрам (CPU Affinity)',
    }
    
    for mode in df['Mode'].unique():
        if mode not in colors_map:
            continue
        mode_data = df[df['Mode'] == mode].sort_values('ThreadCount')
        plt.plot(
            mode_data['ThreadCount'],
            mode_data['RPS'],
            linewidth=2.5 if mode != 'No-Affinity' else 1.8,
            label=mode_labels.get(mode, mode),
            color=colors_map.get(mode, '#000000')
        )
        
    plt.title("Анализ многопоточной масштабируемости (ALT + 4-ary)", fontweight='bold', pad=15, fontsize=13)
    plt.xlabel("Число рабочих потоков", fontsize=11)
    plt.ylabel("Запросы в секунду (RPS)", fontsize=11)
    plt.xticks(thread_counts)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(frameon=True, facecolor='white', edgecolor='#e0e0e0', loc='upper left')
    
    plt.tight_layout()
    plt.savefig(save_path, bbox_inches='tight', dpi=200)
    plt.close()
    print(f"  [Saved] Multithreading scalability plot saved to: {save_path}")

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
        y_label='Производительность QPS (запросов/сек)',
        title='Производительность алгоритмов поиска пути (QPS) в зависимости от длины маршрута',
        save_path=os.path.join(results_dir, 'qps_comparison.png'),
        log_scale=True,
        formula_lambda=lambda x: 1000.0 / x['TimeMs']
    )
    
    # 3. Plot Visited Nodes (Количество раскрытых узлов)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='VisitedNodes',
        y_label='Количество раскрытых узлов',
        title='Размер исследованного пространства поиска (раскрытые узлы) в зависимости от длины маршрута',
        save_path=os.path.join(results_dir, 'visited_nodes_comparison.png'),
        log_scale=True
    )
    
    # 4. Plot Iteration Time (Время одной итерации / раскрытия в наносекундах)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='IterationTimeNs',
        y_label='Время шага поиска (наносекунды)',
        title='Вычислительная сложность обработки одного узла в зависимости от длины маршрута',
        save_path=os.path.join(results_dir, 'iteration_time_comparison.png'),
        log_scale=False,
        formula_lambda=lambda x: (x['TimeMs'] * 1e6) / x['VisitedNodes'].replace(0, 1)
    )
    
    # 5. Plot Queue Operations Count (Количество push+pop операций)
    plot_metric_vs_complexity(
        df, x_values,
        metric_col='QueueOps',
        y_label='Количество операций с очередью (Push + Pop)',
        title='Интенсивность обращений к очереди приоритетов (Push + Pop) в зависимости от длины маршрута',
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
    
    # 9. Multithreading scalability plot (Affinity vs No-Affinity)
    mt_csv = os.path.abspath(os.path.join(script_dir, "..", "stats", "multithreading_results.csv"))
    plot_multithreading_scalability(mt_csv, os.path.join(results_dir, 'multithreading_scalability.png'))
    
    print("\n🎉 Analysis completed! All premium scientific charts have been saved to benchmarks/traffic-core/results/\n")
 
if __name__ == "__main__":
    main()
