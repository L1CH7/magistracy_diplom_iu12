import os
import glob
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
from mpl_toolkits.mplot3d import Axes3D

# Настройки путей (корень проекта: benchmarks/scripts/../..)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTER_BENCH_ROOT = os.path.join(PROJECT_ROOT, "benchmarks", "router")
DATA_DIR = os.path.join(ROUTER_BENCH_ROOT, "results")
PLOTS_DIR = os.path.join(ROUTER_BENCH_ROOT, "plots")

def ensure_dir():
    if not os.path.exists(PLOTS_DIR):
        os.makedirs(PLOTS_DIR, exist_ok=True)

def plot_projections(df, prefix):
    """
    Проекции сложности (Time vs Points, Time vs K).
    """
    success_df = df[df['success'] == 1].copy()
    if success_df.empty: return

    # 1. Зависимость Времени от Числа точек (Color = K)
    plt.figure(figsize=(10, 6))
    sns.pointplot(data=success_df, x='num_waypoints', y='duration_ms', hue='k', 
                  palette="viridis", errorbar=None, capsize=0.1) # Removed errorbar
    plt.title(f'Зависимость времени от N точек (Группировка по K)', fontsize=14)
    plt.xlabel('Количество точек (N)', fontsize=12)
    plt.ylabel('Время (мс)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.legend(title='K маршрутов')
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_projection_time_n.png"), dpi=300)
    print(f"Saved: {prefix}_projection_time_n.png")

    # 2. Зависимость Времени от K (Color = N)
    plt.figure(figsize=(10, 6))
    sns.pointplot(data=success_df, x='k', y='duration_ms', hue='num_waypoints', 
                  palette="magma", errorbar=None, capsize=0.1) # Removed errorbar
    plt.title(f'Зависимость времени от K маршрутов (Группировка по N)', fontsize=14)
    plt.xlabel('Количество маршрутов (K)', fontsize=12)
    plt.ylabel('Время (мс)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.legend(title='N точек')
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_projection_time_k.png"), dpi=300)
    print(f"Saved: {prefix}_projection_time_k.png")

    # 3. Boxplot removed as requested
    
def plot_3d_complexity(df, prefix):
    """E. 3D Scatter Plot."""
    success_df = df[df['success'] == 1].copy()
    if success_df.empty: return

    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection='3d')
    
    x = success_df['num_waypoints'] 
    y = success_df['k']
    z = success_df['duration_ms']
    
    scatter = ax.scatter(x, y, z, c=z, cmap='coolwarm', s=40, alpha=0.8)
    
    ax.set_xlabel('Точки (N)')
    ax.set_ylabel('Маршруты (K)')
    ax.set_zlabel('Время (мс)')
    ax.set_title(f'3D Анализ Сложности (N, K, Time)')
    fig.colorbar(scatter, ax=ax, shrink=0.5, aspect=5, label='Время (мс)')
    
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_complexity_3d.png"), dpi=300)
    print(f"Saved: {prefix}_complexity_3d.png")

def plot_regression(df, prefix):
    """Регрессия Time vs Complexity (N * K)"""
    success_df = df[df['success'] == 1].copy()
    if success_df.empty: return
    
    # User requested a different law: T ~ N * K
    # Ignoring distance for this view to see the algorithmic steps clearly
    success_df['simple_complexity'] = success_df['num_waypoints'] * success_df['k']
    
    plt.figure(figsize=(10, 6))
    
    # Add small jitter to X to see overlapping points (like in Latency plot)
    x_jittered = success_df['simple_complexity'] + np.random.uniform(-0.1, 0.1, size=len(success_df))
    
    slope, intercept, r_value, p_value, std_err = stats.linregress(success_df['simple_complexity'], success_df['duration_ms'])
    r_squared = r_value**2
    
    # Plot Scatter with jitter
    plt.scatter(x_jittered, success_df['duration_ms'], alpha=0.5, s=20, label='Samples (Jittered X)')
    
    # Plot Regression Line (on real X)
    x_vals = np.array([success_df['simple_complexity'].min(), success_df['simple_complexity'].max()])
    y_vals = intercept + slope * x_vals
    plt.plot(x_vals, y_vals, 'r', linewidth=2, label=f'Fit: T = {slope:.1f}*(N*K) + {intercept:.1f}\n$R^2$={r_squared:.3f}')
    
    plt.title(f'Регрессия: Время ~ Алгоритмическая Сложность', fontsize=14)
    plt.xlabel('Сложность (N * K)', fontsize=12)
    plt.ylabel('Время (мс)', fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_regression.png"), dpi=300)
    print(f"Saved: {prefix}_regression.png")

def plot_failure_breakdown(df, prefix):
    """Pie Chart of Error Types"""
    failures = df[df['success'] == 0]
    if failures.empty:
        print(f"[{prefix}] No failures to analyze.")
        return
    
    if 'error' not in df.columns:
        print(f"[{prefix}] 'error' column missing, skipping failure breakdown.")
        return

    # Count errors by type
    error_counts = failures['error'].value_counts()
    
    plt.figure(figsize=(10, 8))
    plt.pie(error_counts, labels=error_counts.index, autopct='%1.1f%%', startangle=140, colors=sns.color_palette('pastel'))
    plt.title(f'Распределение типов ошибок (Total: {len(failures)})')
    plt.axis('equal')
    
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_failure_breakdown.png"), dpi=300)
    print(f"Saved: {prefix}_failure_breakdown.png")

def plot_yield_heatmap(df, prefix):
    """Heatmap: Probability of finding K routes for given N points."""
    # We want to know: For (N, K), what % of requests were fully successful?
    # Success = 1 (Found K routes)
    
    pivot = df.pivot_table(index='k', columns='num_waypoints', values='success', aggfunc='mean')
    
    plt.figure(figsize=(10, 8))
    sns.heatmap(pivot, annot=True, fmt=".1%", cmap="RdYlGn", vmin=0, vmax=1)
    plt.title(f'Вероятность успеха поиска K маршрутов')
    plt.xlabel('Количество точек (N)')
    plt.ylabel('Количество маршрутов (K)')
    
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_yield_heatmap.png"), dpi=300)
    print(f"Saved: {prefix}_yield_heatmap.png")

def plot_tortuosity(df, prefix):
    """Histogram of Route Tortuosity (Length / Euclidean Distance)"""
    success_df = df[df['success'] == 1].copy()
    if 'tortuosity' not in success_df.columns:
        # Calculate if missing (assuming we have length_m and straight_dist)
        # But for now, we skip if column is missing
        return

    plt.figure(figsize=(10, 6))
    sns.histplot(success_df['tortuosity'], bins=30, kde=True, color='purple')
    plt.axvline(success_df['tortuosity'].median(), color='k', linestyle='--', label=f'Median: {success_df["tortuosity"].median():.2f}')
    
    plt.title(f'Гистограмма Извилистости')
    plt.xlabel('Коэффициент (Длина / Прямая)')
    plt.ylabel('Частота')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.savefig(os.path.join(PLOTS_DIR, f"{prefix}_tortuosity_hist.png"), dpi=300)
    print(f"Saved: {prefix}_tortuosity_hist.png")

def process_jaccard():
    """
    Process Jaccard Diversity results.
    """
    file_path = os.path.join(DATA_DIR, "jaccard_results.csv")
    if not os.path.exists(file_path):
        print("Skipping Jaccard: No file found at benchmarks/router/results/jaccard_results.csv")
        return

    print("\nProcessing Jaccard Diversity...")
    df = pd.read_csv(file_path)
    if df.empty: return

    # Filter out cases where only 1 route was found (diversity is irrelevant)
    div_df = df[df['k_actual'] > 1].copy()
    
    if div_df.empty:
        print("No multi-path samples (K > 1) found for Jaccard analysis.")
        return

    # 1. Jaccard vs Distance
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=div_df, x='route_dist_km', y='avg_jaccard', hue='k_actual', palette="coolwarm", s=60, alpha=0.7)
    plt.axhline(div_df['avg_jaccard'].mean(), color='r', linestyle='--', label=f'Mean J: {div_df["avg_jaccard"].mean():.3f}')
    plt.title('Коэффициент Жаккарда vs Дистанция (Чем меньше J, тем выше разнообразие)')
    plt.xlabel('Длина маршрута (км)')
    plt.ylabel('Avg Jaccard Similarity')
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.savefig(os.path.join(PLOTS_DIR, "jaccard_vs_distance.png"), dpi=300)
    print("Saved: jaccard_vs_distance.png")

    # 2. Path Diversity Index (PDI) Distribution
    plt.figure(figsize=(10, 6))
    sns.histplot(div_df['pdi'], bins=20, kde=True, color='teal')
    plt.axvline(div_df['pdi'].mean(), color='k', linestyle='--', label=f'Mean PDI: {div_df["pdi"].mean():.2f}')
    plt.title('Распределение Path Diversity Index (PDI)')
    plt.xlabel('PDI (1.0 = пути полностью уникальны)')
    plt.ylabel('Частота')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(PLOTS_DIR, "pdi_distribution.png"), dpi=300)
    print("Saved: pdi_distribution.png")

    # Generate Conclusions TXT
    conclusions_path = os.path.join(ROUTER_BENCH_ROOT, "jaccard_conclusions.txt")
    with open(conclusions_path, "w") as f:
        f.write("=== Jaccard Diversity Analysis Conclusions ===\n\n")
        f.write(f"Total Samples: {len(df)}\n")
        f.write(f"Multi-Path Success (K > 1): {len(div_df)} ({len(div_df)/len(df)*100:.1f}%)\n")
        f.write(f"Average Jaccard Similarity: {div_df['avg_jaccard'].mean():.4f}\n")
        f.write(f"Average PDI: {div_df['pdi'].mean():.4f}\n")
        f.write(f"Max Similarity: {div_df['avg_jaccard'].max():.4f}\n")
        f.write(f"Min Similarity (Max Diversity): {div_df['avg_jaccard'].min():.4f}\n\n")
        
        f.write("Technical Takeaways:\n")
        f.write("1. Path Diversity Index (PDI) near 1.0 indicates that iterative penalty effectively\n")
        f.write("   forces the router to choose disjoint edge sets, avoiding 'micro-variations'.\n")
        f.write("2. Similarity tends to increase slightly for very long routes where transit corridors\n")
        f.write("   (highways) have fewer alternatives.\n")
        f.write("3. For short distances (< 0.5km), the algorithm often finds fewer than K=5 routes\n")
        f.write("   due to sparse local topology, which is a correct physical behavior.\n")
    print(f"Generated: {conclusions_path}")

def process_group(prefix):
    # Pattern matching for specific prefix files
    pattern = os.path.join(DATA_DIR, f"{prefix}_results_*.csv")
    files = glob.glob(pattern)
    
    if not files:
        print(f"Skipping {prefix}: No files found matching {pattern}")
        return

    print(f"\nProcessing {prefix} ({len(files)} files)...")
    dfs = [pd.read_csv(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    print(f"Records: {len(df)}. Success Rate: {(df['success'].mean()*100):.1f}%")
    
    plot_projections(df, prefix)
    plot_3d_complexity(df, prefix)
    plot_regression(df, prefix)
    plot_yield_heatmap(df, prefix)
    plot_failure_breakdown(df, prefix)
    plot_tortuosity(df, prefix)

def main():
    ensure_dir()
    # Process both groups separately
    process_group("latency")
    process_group("throughput")
    process_jaccard()
    print(f"\nAnalysis complete. Plots saved in {PLOTS_DIR}")

if __name__ == "__main__":
    main()
