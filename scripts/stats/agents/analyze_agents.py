#!/usr/bin/env python3
import sys
import os
import glob
import argparse
import pandas as pd
import matplotlib.pyplot as plt

def analyze_csv(csv_path: str):
    if not os.path.exists(csv_path):
        print(f"[!] Файл не найден: {csv_path}")
        sys.exit(1)

    print("=== НАУЧНО-АНАЛИТИЧЕСКИЙ ОТЧЕТ ДИАГНОСТИКИ АГЕНТОВ ===")
    print(f"Файл данных: {os.path.basename(csv_path)}")
    print("-" * 75)

    df = pd.read_csv(csv_path)
    if df.empty:
        print("[!] Ошибка: CSV файл пуст.")
        sys.exit(1)

    sim_time_min = df["SimTime"].min()
    sim_time_max = df["SimTime"].max()
    duration = sim_time_max - sim_time_min

    avg_sample = df["SampleCount"].mean()
    avg_free = df["FreeFlowCount"].mean()
    avg_stuck = df["StuckQueueCount"].mean()
    avg_virt = df["VirtualBufferCount"].mean()
    avg_inactive = df.get("InactiveCount", pd.Series([0])).mean()

    max_stuck_sec = df["MaxStuckSec"].max()
    mean_stuck_sec = df["AvgStuckSec"].mean()
    avg_speed_mps = df["AvgSpeedMps"].mean()
    max_unique_bottlenecks = df["UniqueStuckEdges"].max()

    avg_rtot = df.get("AvgRouteTotal", pd.Series([0])).mean()
    avg_prog = df.get("AvgRouteProgressPct", pd.Series([0])).mean()
    avg_tsec = df.get("AvgTripSec", pd.Series([0])).mean()
    max_limbo = df.get("LimboPhantomCount", pd.Series([0])).max()
    avg_edge0 = df.get("Edge0Count", pd.Series([0])).mean()

    driving_total = avg_free + avg_stuck + avg_virt
    stuck_ratio_pct = (avg_stuck / driving_total * 100.0) if driving_total > 0 else 0.0

    print(f"Общие параметры выборки:")
    print(f"  ├─ Длительность замера:  {duration:.1f} сек. симуляции (от {sim_time_min:.1f} до {sim_time_max:.1f})")
    print(f"  ├─ Размер выборки:       {avg_sample:.0f} агентов/токен")
    print(f"  └─ Измерений телеметрии: {len(df)} точек")
    print()
    print(f"Распределение статусов на дорогах:")
    print(f"  ├─ Активно на дорогах:           {driving_total:.1f} авто")
    print(f"  ├─ Свободный поток (FREE_FLOW):   {avg_free:.1f} авто ({(avg_free/max(1,driving_total))*100:.1f}%)")
    print(f"  ├─ В очереди затора (0 м/с):       {avg_stuck:.1f} авто ({stuck_ratio_pct:.1f}%)")
    print(f"  ├─ В виртуальном буфере SUMO:     {avg_virt:.1f} авто ({(avg_virt/max(1,driving_total))*100:.1f}%)")
    if avg_inactive > 0:
        print(f"  └─ Неактивны (INACTIVE в замере): {avg_inactive:.1f} авто")
    print()
    print(f"Метрики качества маршрутов и аномалий:")
    print(f"  ├─ Средняя длина маршрута:      {avg_rtot:.1f} рёбер")
    print(f"  ├─ Среднее время в пути:        {avg_tsec:.1f} сек.")
    print(f"  ├─ Средний прогресс пути:       {avg_prog:.1f}%")
    print(f"  ├─ Фантомные агенты (Limbo):    {max_limbo:.0f} макс (аномалии без маршрута)")
    print(f"  └─ Агенты на фантомном Edge 0:  {avg_edge0:.1f} авто среднее")
    print()
    print(f"Метрики простоев и скоростей:")
    print(f"  ├─ Среднее время в заторе:      {mean_stuck_sec:.1f} сек.")
    print(f"  ├─ Максимальное время в заторе: {max_stuck_sec:.1f} сек.")
    print(f"  ├─ Средняя скорость потока:     {avg_speed_mps:.2f} м/с ({avg_speed_mps*3.6:.1f} км/ч)")
    print(f"  └─ Макс. уникальных узких рёбер:{max_unique_bottlenecks} рёбер одновременно")
    print("-" * 75)

    # Plotting Dashboard
    fig, axs = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(f"Аналитика поведения выборки агентов ({os.path.basename(csv_path)})", fontsize=14, fontweight="bold")

    time = df["SimTime"] / 3600.0  # Hours

    # 1. Status Distribution Over Time
    axs[0, 0].plot(time, df["FreeFlowCount"], color="#2ca02c", linewidth=2.0, label="Free Flow (Едут)")
    axs[0, 0].plot(time, df["StuckQueueCount"], color="#d62728", linewidth=2.0, label="Stuck Queue (Стоят 0 м/с)")
    axs[0, 0].plot(time, df["VirtualBufferCount"], color="#9467bd", linewidth=2.0, label="Virtual Buffer (Буфер SUMO)")
    axs[0, 0].set_title("Динамика статусов агентов на дорогах")
    axs[0, 0].set_xlabel("Время симуляции (часы)")
    axs[0, 0].set_ylabel("Количество агентов")
    axs[0, 0].grid(True, linestyle="--", alpha=0.6)
    axs[0, 0].legend(loc="upper right")

    # 2. Route Progress & Discrepancies
    if "AvgRouteProgressPct" in df.columns:
        axs[0, 1].plot(time, df["AvgRouteProgressPct"], color="#1f77b4", linewidth=2.0, label="Средний прогресс маршрута (%)")
    if "LimboPhantomCount" in df.columns:
        axs[0, 1].plot(time, df["LimboPhantomCount"], color="#d62728", linestyle="--", linewidth=1.5, label="Фантомы без маршрута")
    axs[0, 1].set_title("Прогресс движения и обнаружение аномалий")
    axs[0, 1].set_xlabel("Время симуляции (часы)")
    axs[0, 1].set_ylabel("Процент / Количество")
    axs[0, 1].grid(True, linestyle="--", alpha=0.6)
    axs[0, 1].legend(loc="upper left")

    # 3. Average Speed Evolution
    axs[1, 0].plot(time, df["AvgSpeedMps"] * 3.6, color="#008080", linewidth=2.0, label="Средняя скорость (км/ч)")
    axs[1, 0].axhline(y=5.0, color="#d62728", linestyle=":", label="Порог глухого затора (5 км/ч)")
    axs[1, 0].set_title("Динамика средней скорости потока")
    axs[1, 0].set_xlabel("Время симуляции (часы)")
    axs[1, 0].set_ylabel("Скорость (км/ч)")
    axs[1, 0].grid(True, linestyle="--", alpha=0.6)
    axs[1, 0].legend(loc="lower right")

    # 4. Spillback Wait Time
    axs[1, 1].plot(time, df["AvgStuckSec"], color="#ff7f0e", linewidth=2.0, label="Средний простой (сек)")
    axs[1, 1].plot(time, df["MaxStuckSec"], color="#d62728", linestyle="--", linewidth=1.5, label="Макс. простой (сек)")
    axs[1, 1].set_title("Время простоя в заторах (Spillback Wait Time)")
    axs[1, 1].set_xlabel("Время симуляции (часы)")
    axs[1, 1].set_ylabel("Секунды ожидания")
    axs[1, 1].grid(True, linestyle="--", alpha=0.6)
    axs[1, 1].legend(loc="upper left")

    plt.tight_layout()

    out_png = csv_path.replace(".csv", "_dashboard.png")
    plt.savefig(out_png, dpi=200)
    print(f"[+] График анализа агентов сохранен: {os.path.basename(out_png)}")

def main():
    parser = argparse.ArgumentParser(description="Visualize Agent Sample Telemetry CSV")
    parser.add_argument("csv", nargs="?", help="Path to CSV file. If omitted, uses latest file in scripts/stats/agents/")
    args = parser.parse_args()

    csv_file = args.csv
    if not csv_file:
        agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        files = glob.glob(os.path.join(agents_dir, "*.csv"))
        if not files:
            print(f"[!] Файлы CSV не найдены в {agents_dir}")
            sys.exit(1)
        csv_file = max(files, key=os.path.getmtime)
        print(f"[*] Используется последний CSV файл: {os.path.basename(csv_file)}")

    analyze_csv(csv_file)

if __name__ == "__main__":
    main()
