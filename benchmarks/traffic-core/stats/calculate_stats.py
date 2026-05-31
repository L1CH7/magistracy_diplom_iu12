import pandas as pd
import numpy as np

df = pd.read_csv('/home/lich/dev/bmstu/diplom-iu12/magistracy-diplom-iu12/benchmarks/traffic-core/stats/run_results.csv')
df = df[df['Crashed'] == 0]

print("=== Unique Algorithms and Queues ===")
print("Algorithms:", df['Algorithm'].unique())
print("Queues:", df['Queue'].unique())

summary_records = []
for (algo, queue), group in df.groupby(['Algorithm', 'Queue']):
    mean_time = group['TimeMs'].mean()
    mean_qps = 1000.0 / group['TimeMs'].mean() # QPS is 1000 / mean_time_per_route
    mean_nodes = group['VisitedNodes'].mean()
    mean_ops = (group['PushCount'] + group['PopCount']).mean()
    mean_push_cycles = group['AvgPushCycles'].mean()
    mean_pop_cycles = group['AvgPopCycles'].mean()
    mean_overhead = (group['QueueTimeMs'] / group['TimeMs']).mean() * 100.0
    
    # Метрики точности (относительно эталона Dijkstra)
    mean_error = group['RelativeErrorPct'].mean() if 'RelativeErrorPct' in group.columns else 0.0
    max_error = group['RelativeErrorPct'].max() if 'RelativeErrorPct' in group.columns else 0.0
    exact_match = (group['IsExactMatch'].mean() * 100.0) if 'IsExactMatch' in group.columns else 100.0
    
    summary_records.append({
        'Algorithm': algo,
        'Queue': queue,
        'MeanTimeMs': mean_time,
        'QPS': mean_qps,
        'MeanNodes': mean_nodes,
        'MeanOps': mean_ops,
        'MeanPushCycles': mean_push_cycles,
        'MeanPopCycles': mean_pop_cycles,
        'MeanOverheadPct': mean_overhead,
        'MeanRelativeErrorPct': mean_error,
        'MaxRelativeErrorPct': max_error,
        'ExactMatchRatePct': exact_match
    })

summary_df = pd.DataFrame(summary_records)
summary_df.to_csv('/home/lich/dev/bmstu/diplom-iu12/magistracy-diplom-iu12/benchmarks/traffic-core/stats/stats_summary.csv', index=False)

with open('/home/lich/dev/bmstu/diplom-iu12/magistracy-diplom-iu12/benchmarks/traffic-core/stats/stats_summary.txt', 'w') as f:
    f.write("=== GLOBAL BENCHMARK SUMMARY ===\n\n")
    for rec in summary_records:
        f.write(f"Algorithm: {rec['Algorithm']}, Queue: {rec['Queue']}\n")
        f.write(f"  Mean Time: {rec['MeanTimeMs']:.4f} ms\n")
        f.write(f"  QPS: {rec['QPS']:.2f}\n")
        f.write(f"  Mean Visited Nodes: {rec['MeanNodes']:.1f}\n")
        f.write(f"  Mean Queue Ops (Push+Pop): {rec['MeanOps']:.1f}\n")
        f.write(f"  Mean Push Cycles: {rec['MeanPushCycles']:.2f}\n")
        f.write(f"  Mean Pop Cycles: {rec['MeanPopCycles']:.2f}\n")
        f.write(f"  Mean Queue Overhead: {rec['MeanOverheadPct']:.2f}%\n")
        f.write(f"  Mean Relative Error (MRE): {rec['MeanRelativeErrorPct']:.4f}%\n")
        f.write(f"  Max Relative Error (MaxRE): {rec['MaxRelativeErrorPct']:.4f}%\n")
        f.write(f"  Exact Match Rate (EMR): {rec['ExactMatchRatePct']:.2f}%\n\n")

print("Summary successfully written to stats_summary.txt")
