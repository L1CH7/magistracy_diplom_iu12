#!/usr/bin/env python3
import os
import csv
import sys
import glob
import numpy as np

# Style settings for console output
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_CYAN = "\033[36m"
C_MAGENTA = "\033[35m"

def pearson_correlation(x, y):
    """Calculate Pearson correlation coefficient between two lists."""
    n = len(x)
    if n == 0:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    denom_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    denom_y = sum((y[i] - mean_y) ** 2 for i in range(n))
    
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return numerator / ((denom_x * denom_y) ** 0.5)

def load_csv_data(filepath):
    """Load and parse telemetry data from CSV file."""
    data = {
        "SimTime": [],
        "TTI": [],
        "ActiveAgents": [],
        "WaitingReroute": [],
        "CompletedTrips": [],
        "DynamicReroutes": [],
        "BlackZones": [],
        "RedZones": [],
        "YellowZones": [],
        "RouterRPS": [],
        "SavedDuplicates": [],
        "RouterLoad": [],
        "GreenZones": [],
        "VisitedNodes": [],
        "RouteCycles": [],
        "WaitingSpawn": [],
        "RouteTimeMaxUs": [],
        "RouteTimeAvgUs": [],
        "RouterWaitTimeUs": []
    }
    
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data["SimTime"].append(float(row["SimTime"]))
            data["TTI"].append(float(row["TTI"]))
            data["ActiveAgents"].append(int(row["ActiveAgents"]))
            data["WaitingReroute"].append(int(row["WaitingReroute"]))
            data["CompletedTrips"].append(int(row["CompletedTrips"]))
            data["DynamicReroutes"].append(int(row["DynamicReroutes"]))
            data["BlackZones"].append(int(row["BlackZones"]))
            data["RedZones"].append(int(row["RedZones"]))
            data["YellowZones"].append(int(row["YellowZones"]))
            data["RouterRPS"].append(float(row["RouterRPS"]))
            data["SavedDuplicates"].append(int(row["SavedDuplicates"]))
            data["RouterLoad"].append(float(row["RouterLoad"]))
            data["GreenZones"].append(int(row.get("GreenZones", 0)))
            data["VisitedNodes"].append(float(row.get("VisitedNodes", 0.0)))
            data["RouteCycles"].append(float(row.get("RouteCycles", 0.0)))
            data["WaitingSpawn"].append(int(row.get("WaitingSpawn", 0)))
            data["RouteTimeMaxUs"].append(float(row.get("RouteTimeMaxUs", 0.0)))
            data["RouteTimeAvgUs"].append(float(row.get("RouteTimeAvgUs", 0.0)))
            data["RouterWaitTimeUs"].append(float(row.get("RouterWaitTimeUs", 0.0)))
            
    return data

def plot_comparison(output_png, time_old, time_new, data_old, data_new, 
                    overlap_times, old_overlap_interp, new_overlap_interp, t_start, t_end):
    """Generate high-quality multi-panel scientific dashboard comparing two runs."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"\n{C_YELLOW}[!] Для построения графиков установите matplotlib: pip install matplotlib{C_RESET}")
        return

    print(f"{C_BOLD}{C_GREEN}Генерация сравнительных графиков...{C_RESET}")
    
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Liberation Sans']
    plt.rcParams['axes.edgecolor'] = '#cccccc'
    plt.rcParams['axes.linewidth'] = 0.8
    
    # 4x2 Grid for comprehensive metrics
    fig, axs = plt.subplots(4, 2, figsize=(16, 20), dpi=150)
    fig.suptitle("СРАВНИТЕЛЬНЫЙ АНАЛИЗ АЛГОРИТМОВ МАРШРУТИЗАЦИИ\n"
                 "BPR Включен (Traffic Router BPR) vs BPR Отключен (Без BPR)", 
                 fontsize=16, fontweight='bold', y=0.98)
    
    # Color scheme
    c_bpr_on = '#1f77b4'   # Premium Blue for BPR Enabled (old)
    c_bpr_off = '#d62728'  # Premium Red for BPR Disabled (new)
    
    # Helper to apply consistent styling
    def style_subplot(ax, title, ylabel):
        ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
        ax.set_xlabel("Время симуляции (сек)", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.grid(True, linestyle=':', alpha=0.6)
        # Highlight overlap window
        ax.axvspan(t_start, t_end, color='#2ca02c', alpha=0.08, label='Окно сравнения (Overlap)')
        ax.axvline(t_start, color='#2ca02c', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.axvline(t_end, color='#2ca02c', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none', framealpha=0.9)

    # 1. Travel Time Index (TTI)
    axs[0, 0].plot(time_old, data_old["TTI"], color=c_bpr_on, linewidth=2.0, label='BPR Включен (Old)')
    axs[0, 0].plot(time_new, data_new["TTI"], color=c_bpr_off, linewidth=2.0, label='BPR Отключен (New)')
    axs[0, 0].axhline(1.0, color='gray', linestyle='-.', linewidth=0.8, alpha=0.7, label='Порог Free-Flow (1.0)')
    style_subplot(axs[0, 0], "Динамика Индекса Задержки (TTI)", "Коэффициент TTI")

    # 2. Black Zones (Severe Congestion)
    axs[0, 1].plot(time_old, data_old["BlackZones"], color=c_bpr_on, linewidth=2.0, label='BPR Включен (Old)')
    axs[0, 1].plot(time_new, data_new["BlackZones"], color=c_bpr_off, linewidth=2.0, label='BPR Отключен (New)')
    style_subplot(axs[0, 1], "Заторы: Черные зоны (Задержка >= 2x)", "Количество ребер сети")

    # 3. Red & Yellow Zones (High & Moderate Load)
    axs[1, 0].plot(time_old, data_old["RedZones"], color=c_bpr_on, linewidth=2.0, label='Красные: BPR ON')
    axs[1, 0].plot(time_new, data_new["RedZones"], color=c_bpr_off, linewidth=2.0, label='Красные: BPR OFF')
    axs[1, 0].plot(time_old, data_old["YellowZones"], color='#ff7f0e', linestyle='--', linewidth=1.5, label='Желтые: BPR ON')
    axs[1, 0].plot(time_new, data_new["YellowZones"], color='#bcbd22', linestyle='--', linewidth=1.5, label='Желтые: BPR OFF')
    style_subplot(axs[1, 0], "Загрузка сети: Красные и Желтые зоны", "Количество ребер сети")

    # 4. Cumulative Net Completed Trips (since t_start)
    # Calculate net curves for full plotting (where defined since t_start)
    old_start_val = np.interp(t_start, time_old, data_old["CompletedTrips"])
    new_start_val = np.interp(t_start, time_new, data_new["CompletedTrips"])
    
    # Net completed trips over full time for visualization (filtered >= t_start)
    vis_time_old = [t for t in time_old if t >= t_start]
    vis_comp_old = [c - old_start_val for t, c in zip(time_old, data_old["CompletedTrips"]) if t >= t_start]
    
    vis_time_new = [t for t in time_new if t >= t_start]
    vis_comp_new = [c - new_start_val for t, c in zip(time_new, data_new["CompletedTrips"]) if t >= t_start]
    
    axs[1, 1].plot(vis_time_old, vis_comp_old, color=c_bpr_on, linewidth=2.0, label='BPR Включен (Old)')
    axs[1, 1].plot(vis_time_new, vis_comp_new, color=c_bpr_off, linewidth=2.0, label='BPR Отключен (New)')
    style_subplot(axs[1, 1], f"Накопленные совершенные поездки (с t={t_start:.0f} сек)", "Количество доехавших авто")

    # 5. Router performance (RPS)
    axs[2, 0].plot(time_old, data_old["RouterRPS"], color=c_bpr_on, linewidth=2.0, label='BPR Включен (Old)')
    axs[2, 0].plot(time_new, data_new["RouterRPS"], color=c_bpr_off, linewidth=2.0, label='BPR Отключен (New)')
    style_subplot(axs[2, 0], "Вычислительная скорость роутера (RPS)", "Запросы в секунду")

    # 6. MPR Queue Size (Waiting Reroute)
    axs[2, 1].plot(time_old, data_old["WaitingReroute"], color=c_bpr_on, linewidth=2.0, label='BPR Включен (Old)')
    axs[2, 1].plot(time_new, data_new["WaitingReroute"], color=c_bpr_off, linewidth=2.0, label='BPR Отключен (New)')
    style_subplot(axs[2, 1], "Размер очереди динамического перестроения MPR", "Количество агентов в очереди")

    # 7. Pathfinding Search Latency comparison (Max & Avg in milliseconds)
    # Convert Us to Ms
    avg_ms_old = [t / 1000.0 for t in data_old.get("RouteTimeAvgUs", [0.0]*len(time_old))]
    avg_ms_new = [t / 1000.0 for t in data_new.get("RouteTimeAvgUs", [0.0]*len(time_new))]
    max_ms_old = [t / 1000.0 for t in data_old.get("RouteTimeMaxUs", [0.0]*len(time_old))]
    max_ms_new = [t / 1000.0 for t in data_new.get("RouteTimeMaxUs", [0.0]*len(time_new))]
    
    axs[3, 0].plot(time_old, avg_ms_old, color='#1f77b4', linewidth=1.5, label='Среднее (BPR ON)')
    axs[3, 0].plot(time_new, avg_ms_new, color='#d62728', linestyle='--', linewidth=1.5, label='Среднее (BPR OFF)')
    
    axs[3, 0].plot(time_old, max_ms_old, color='#ff7f0e', linewidth=1.5, label='Пиковое (BPR ON)')
    axs[3, 0].plot(time_new, max_ms_new, color='#9467bd', linestyle='--', linewidth=1.5, label='Пиковое (BPR OFF)')
    
    style_subplot(axs[3, 0], "Задержка вычисления маршрута A* (Max/Avg)", "Время расчета (мс)")

    # 8. Router Search Space & Barrier Synchronization Idle Time (Double Y-Axis)
    ax_left = axs[3, 1]
    ax_right = ax_left.twinx()
    
    l1 = ax_left.plot(time_old, data_old["VisitedNodes"], color='#1f77b4', linewidth=1.8, label='Вершины (BPR ON)')
    l2 = ax_left.plot(time_new, data_new["VisitedNodes"], color='#d62728', linestyle='--', linewidth=1.8, label='Вершины (BPR OFF)')
    
    # Convert Us to Seconds
    wait_sec_old = [w / 1e6 for w in data_old.get("RouterWaitTimeUs", [0.0]*len(time_old))]
    wait_sec_new = [w / 1e6 for w in data_new.get("RouterWaitTimeUs", [0.0]*len(time_new))]
    
    l3 = ax_right.plot(time_old, wait_sec_old, color='#ff7f0e', linewidth=1.5, label='Простой WaitForAll (BPR ON)')
    l4 = ax_right.plot(time_new, wait_sec_new, color='#2ca02c', linestyle='--', linewidth=1.5, label='Простой WaitForAll (BPR OFF)')
    
    ax_left.set_title("Пространство поиска & Барьерная синхронизация", fontsize=12, fontweight='bold', pad=10)
    ax_left.set_xlabel("Время симуляции (сек)", fontsize=10)
    ax_left.set_ylabel("Посещенные вершины A* (ед)", fontsize=10)
    ax_right.set_ylabel("Накопленный простой на барьере (сек)", fontsize=10)
    ax_left.grid(True, linestyle=':', alpha=0.6)
    
    # Overlap visualization on ax_left
    ax_left.axvspan(t_start, t_end, color='#2ca02c', alpha=0.08, label='Окно сравнения')
    ax_left.axvline(t_start, color='#2ca02c', linestyle='--', linewidth=0.8, alpha=0.5)
    ax_left.axvline(t_end, color='#2ca02c', linestyle='--', linewidth=0.8, alpha=0.5)
    
    lns = l1 + l2 + l3 + l4
    labs = [l.get_label() for l in lns]
    ax_left.legend(lns, labs, loc='upper left', frameon=True, facecolor='white', edgecolor='none', framealpha=0.9)


    plt.tight_layout()
    plt.subplots_adjust(top=0.92)
    plt.savefig(output_png, bbox_inches='tight')
    plt.close()
    print(f"{C_BOLD}{C_GREEN}[+] График сравнения успешно сохранен: {os.path.basename(output_png)}{C_RESET}")

def compare_runs():
    stats_dir = os.path.dirname(os.path.abspath(__file__))
    
    old_file = None
    new_file = None
    
    # If files are explicitly provided as CLI arguments
    if len(sys.argv) > 2:
        old_file = sys.argv[1]
        new_file = sys.argv[2]
        if not os.path.isabs(old_file):
            old_file = os.path.join(stats_dir, old_file)
        if not os.path.isabs(new_file):
            new_file = os.path.join(stats_dir, new_file)
    else:
        # Auto-discover two latest run files in stats/
        csv_files = glob.glob(os.path.join(stats_dir, "run_*.csv"))
        # Sort by modification time, descending (latest first)
        csv_files.sort(key=os.path.getmtime, reverse=True)
        if len(csv_files) < 2:
            print(f"{C_RED}Ошибка: Найдено менее двух файлов для сравнения в {stats_dir}!{C_RESET}")
            sys.exit(1)
            
        file1 = csv_files[0]
        file2 = csv_files[1]
        
        # Determine BPR ON / OFF roles based on naming or fallback
        # BPR ON is "old" (baseline), BPR OFF is "new" (candidate)
        f1_is_bpr_off = "bpr_off" in os.path.basename(file1) or "BUCKETS_OFF" in os.path.basename(file1)
        f2_is_bpr_off = "bpr_off" in os.path.basename(file2) or "BUCKETS_OFF" in os.path.basename(file2)
        
        if f1_is_bpr_off and not f2_is_bpr_off:
            old_file = file2
            new_file = file1
        elif f2_is_bpr_off and not f1_is_bpr_off:
            old_file = file1
            new_file = file2
        else:
            # Fallback to modification order (older file is old, newer is new)
            if os.path.getmtime(file1) < os.path.getmtime(file2):
                old_file = file1
                new_file = file2
            else:
                old_file = file2
                new_file = file1
                
    if not os.path.exists(old_file) or not os.path.exists(new_file):
        print(f"{C_RED}Ошибка: Один или оба файла телеметрии не найдены!{C_RESET}")
        print(f"Ожидаемые файлы:\n  - {old_file}\n  - {new_file}")
        sys.exit(1)
        
    old_file_name = os.path.basename(old_file)
    new_file_name = os.path.basename(new_file)
    
    print(f"{C_BOLD}{C_CYAN}=== СРАВНИТЕЛЬНЫЙ АНАЛИЗ РАБОТЫ ТРАНСПОРТНОГО РОУТЕРА ==={C_RESET}")
    print(f"Старый запуск (BPR Включен):  {old_file_name}")
    print(f"Новый запуск  (BPR Отключен): {new_file_name}")
    print("-" * 75)
    
    # Load data
    data_old = load_csv_data(old_file)
    data_new = load_csv_data(new_file)
    
    time_old = data_old["SimTime"]
    time_new = data_new["SimTime"]
    
    # Identify overlap window
    t_start = max(time_old[0], time_new[0])
    t_end = min(time_old[-1], time_new[-1])
    
    print(f"{C_BOLD}Параметры запусков и временное окно сравнения:{C_RESET}")
    print(f"  ├─ Временной диапазон старого запуска: {time_old[0]:.1f} → {time_old[-1]:.1f} сек ({len(time_old)} точек)")
    print(f"  ├─ Временной диапазон нового запуска:  {time_new[0]:.1f} → {time_new[-1]:.1f} сек ({len(time_new)} точек)")
    print(f"  └─ {C_GREEN}{C_BOLD}Окно пересечения для сравнения:      {t_start:.1f} → {t_end:.1f} сек{C_RESET}")
    print("")
    
    # Grid of overlap times
    overlap_times = np.array([t for t in time_new if t_start <= t <= t_end])
    n_overlap = len(overlap_times)
    
    if n_overlap < 2:
        print(f"{C_RED}Ошибка: Слишком маленькое окно пересечения ({n_overlap} точек). Невозможно провести сравнение.{C_RESET}")
        sys.exit(1)
        
    # Perform linear interpolation for both to get aligned values
    old_overlap = {}
    new_overlap = {}
    
    metrics_to_compare = ["TTI", "ActiveAgents", "WaitingReroute", "CompletedTrips", 
                          "DynamicReroutes", "BlackZones", "RedZones", "YellowZones", 
                          "RouterRPS", "SavedDuplicates", "RouterLoad"]
    
    for metric in metrics_to_compare:
        old_overlap[metric] = np.interp(overlap_times, time_old, data_old[metric])
        new_overlap[metric] = np.interp(overlap_times, time_new, data_new[metric])
        
    # Calculate differentials for cumulative metrics over the overlap period
    # Net completed trips during overlap
    old_comp_start = np.interp(t_start, time_old, data_old["CompletedTrips"])
    new_comp_start = np.interp(t_start, time_new, data_new["CompletedTrips"])
    net_completed_old = old_overlap["CompletedTrips"][-1] - old_comp_start
    net_completed_new = new_overlap["CompletedTrips"][-1] - new_comp_start
    
    # Net dynamic reroutes during overlap
    old_rer_start = np.interp(t_start, time_old, data_old["DynamicReroutes"])
    new_rer_start = np.interp(t_start, time_new, data_new["DynamicReroutes"])
    net_reroutes_old = old_overlap["DynamicReroutes"][-1] - old_rer_start
    net_reroutes_new = new_overlap["DynamicReroutes"][-1] - new_rer_start
    
    # Net saved duplicates during overlap
    old_saved_start = np.interp(t_start, time_old, data_old["SavedDuplicates"])
    new_saved_start = np.interp(t_start, time_new, data_new["SavedDuplicates"])
    net_saved_old = old_overlap["SavedDuplicates"][-1] - old_saved_start
    net_saved_new = new_overlap["SavedDuplicates"][-1] - new_saved_start
    
    # Mean metrics in overlap
    mean_tti_old = np.mean(old_overlap["TTI"])
    mean_tti_new = np.mean(new_overlap["TTI"])
    
    mean_black_old = np.mean(old_overlap["BlackZones"])
    mean_black_new = np.mean(new_overlap["BlackZones"])
    
    mean_red_old = np.mean(old_overlap["RedZones"])
    mean_red_new = np.mean(new_overlap["RedZones"])
    
    mean_rps_old = np.mean(old_overlap["RouterRPS"])
    mean_rps_new = np.mean(new_overlap["RouterRPS"])
    
    mean_queue_old = np.mean(old_overlap["WaitingReroute"])
    mean_queue_new = np.mean(new_overlap["WaitingReroute"])
    
    mean_load_old = np.mean(old_overlap["RouterLoad"]) * 100.0
    mean_load_new = np.mean(new_overlap["RouterLoad"]) * 100.0
    
    # Peak metrics in overlap
    max_tti_old = np.max(old_overlap["TTI"])
    max_tti_new = np.max(new_overlap["TTI"])
    
    max_black_old = np.max(old_overlap["BlackZones"])
    max_black_new = np.max(new_overlap["BlackZones"])
    
    max_red_old = np.max(old_overlap["RedZones"])
    max_red_new = np.max(new_overlap["RedZones"])
    
    max_rps_old = np.max(old_overlap["RouterRPS"])
    max_rps_new = np.max(new_overlap["RouterRPS"])
    
    max_queue_old = np.max(old_overlap["WaitingReroute"])
    max_queue_new = np.max(new_overlap["WaitingReroute"])

    # Output detailed comparative tables
    print(f"{C_BOLD}1. МЕТРИКИ ЗАДЕРЖКИ (TTI - Travel Time Index) в окне сравнения:{C_RESET}")
    print(f"  ├─ Средний TTI:               BPR ON: {mean_tti_old:.4f}  │  BPR OFF: {mean_tti_new:.4f}  "
          f"│  {C_RED if mean_tti_new > mean_tti_old else C_GREEN}Изменение: {((mean_tti_new - mean_tti_old)/mean_tti_old)*100:+.2f}%{C_RESET}")
    print(f"  ├─ Пиковый TTI:               BPR ON: {max_tti_old:.4f}  │  BPR OFF: {max_tti_new:.4f}  "
          f"│  {C_RED if max_tti_new > max_tti_old else C_GREEN}Изменение: {((max_tti_new - max_tti_old)/max_tti_old)*100:+.2f}%{C_RESET}")
    print(f"  └─ Конечный TTI в окне:        BPR ON: {old_overlap['TTI'][-1]:.4f}  │  BPR OFF: {new_overlap['TTI'][-1]:.4f}  "
          f"│  {C_RED if new_overlap['TTI'][-1] > old_overlap['TTI'][-1] else C_GREEN}Изменение: {((new_overlap['TTI'][-1] - old_overlap['TTI'][-1])/old_overlap['TTI'][-1])*100:+.2f}%{C_RESET}")
    print("")

    print(f"{C_BOLD}2. ЗАВЕРШЕННЫЕ ПОЕЗДКИ И ДИНАМИКА ДВИЖЕНИЯ (внутри окна):{C_RESET}")
    print(f"  ├─ Успешно доехали (авто):    BPR ON: {net_completed_old:.0f}  │  BPR OFF: {net_completed_new:.0f}  "
          f"│  {C_GREEN if net_completed_new > net_completed_old else C_RED}Эффективность: {((net_completed_new - net_completed_old)/net_completed_old)*100:+.2f}%{C_RESET}")
    print(f"  ├─ Темп завершения поездок:   BPR ON: {net_completed_old/(t_end-t_start):.2f} авт/с │  BPR OFF: {net_completed_new/(t_end-t_start):.2f} авт/с "
          f"│  {C_GREEN if net_completed_new > net_completed_old else C_RED}Разница: {((net_completed_new - net_completed_old)/net_completed_old)*100:+.2f}%{C_RESET}")
    print(f"  └─ Динамические объезды MPR:  BPR ON: {net_reroutes_old:.0f}  │  BPR OFF: {net_reroutes_new:.0f}  "
          f"│  Разница в частоте: {((net_reroutes_new - net_reroutes_old)/net_reroutes_old)*100:+.2f}%")
    print("")

    print(f"{C_BOLD}3. СОСТОЯНИЕ ДОРОЖНОЙ СЕТИ И ЗАТОРЫ (в среднем в окне):{C_RESET}")
    print(f"  ├─ Черные зоны (Заторы):     BPR ON: {mean_black_old:.1f}  │  BPR OFF: {mean_black_new:.1f}  "
          f"│  {C_GREEN if mean_black_new < mean_black_old else C_RED}Снижение заторов: {((mean_black_new - mean_black_old)/mean_black_old)*100:+.2f}%{C_RESET}")
    print(f"  ├─ Красные зоны (Нагрузка):   BPR ON: {mean_red_old:.1f}  │  BPR OFF: {mean_red_new:.1f}  "
          f"│  {C_GREEN if mean_red_new < mean_red_old else C_RED}Снижение нагрузки: {((mean_red_new - mean_red_old)/mean_red_old)*100:+.2f}%{C_RESET}")
    print(f"  └─ Пик заторов (черных ребер): BPR ON: {max_black_old:.0f}  │  BPR OFF: {max_black_new:.0f}  "
          f"│  {C_GREEN if max_black_new < max_black_old else C_RED}Снижение пика: {((max_black_new - max_black_old)/max_black_old)*100:+.2f}%{C_RESET}")
    print("")

    print(f"{C_BOLD}4. ПРОИЗВОДИТЕЛЬНОСТЬ ВЫЧИСЛЕНИЙ РОУТЕРА И РЕСУРСЫ:{C_RESET}")
    print(f"  ├─ Средняя скорость роутера: BPR ON: {mean_rps_old:.1f} RPS │  BPR OFF: {mean_rps_new:.1f} RPS "
          f"│  {C_GREEN if mean_rps_new > mean_rps_old else C_YELLOW}Производительность: {((mean_rps_new - mean_rps_old)/mean_rps_old)*100:+.2f}%{C_RESET}")
    print(f"  ├─ Пиковая скорость роутера: BPR ON: {max_rps_old:.1f} RPS │  BPR OFF: {max_rps_new:.1f} RPS "
          f"│  Разница в пике: {((max_rps_new - max_rps_old)/max_rps_old)*100:+.2f}%")
    print(f"  ├─ Загрузка потока роутера:  BPR ON: {mean_load_old:.1f}%   │  BPR OFF: {mean_load_new:.1f}%   "
          f"│  {C_GREEN if mean_load_new < mean_load_old else C_RED}Разгрузка CPU: {((mean_load_old - mean_load_new)/mean_load_old)*100:+.2f}%{C_RESET}")
    print(f"  ├─ Предотвращено дубликатов:  BPR ON: {net_saved_old:.0f}     │  BPR OFF: {net_saved_new:.0f}     "
          f"│  Сбережение вычислений: {((net_saved_new - net_saved_old)/net_saved_old)*100:+.2f}%")
    print(f"  ├─ Средняя очередь MPR:       BPR ON: {mean_queue_old:.1f}   │  BPR OFF: {mean_queue_new:.1f}   "
          f"│  {C_GREEN if mean_queue_new < mean_queue_old else C_RED}Нагрузка очереди: {((mean_queue_new - mean_queue_old)/mean_queue_old)*100:+.2f}%{C_RESET}")
    print(f"  └─ Пиковая очередь MPR:      BPR ON: {max_queue_old:.0f}   │  BPR OFF: {max_queue_new:.0f}   "
          f"│  {C_GREEN if max_queue_new < max_queue_old else C_RED}Пик очереди: {((max_queue_new - max_queue_old)/max_queue_old)*100:+.2f}%{C_RESET}")
    print("")

    # Correlation Analysis
    corr_tti = pearson_correlation(old_overlap["TTI"], new_overlap["TTI"])
    corr_black = pearson_correlation(old_overlap["BlackZones"], new_overlap["BlackZones"])
    corr_queue = pearson_correlation(old_overlap["WaitingReroute"], new_overlap["WaitingReroute"])
    
    print(f"{C_BOLD}5. КОРРЕЛЯЦИОННЫЙ АНАЛИЗ МЕЖДУ СЕРИЯМИ (Синхронность процессов):{C_RESET}")
    print(f"  ├─ Корреляция динамики TTI:    {corr_tti:+.4f} (поведение транспортного потока во времени)")
    print(f"  ├─ Корреляция развития пробок: {corr_black:+.4f} (совпадение критических перегрузок)")
    print(f"  └─ Корреляция очередей MPR:    {corr_queue:+.4f}")
    print("-" * 75)
    
    # Conclusions and Scientific Analysis
    print(f"{C_BOLD}{C_CYAN}ВЫВОДЫ И НАУЧНО-ТЕХНИЧЕСКИЙ АНАЛИЗ:{C_RESET}")
    if mean_tti_new > mean_tti_old:
        print(f"  {C_RED}● Отключение BPR (TRAFFIC_DISABLE_ROUTER_BPR = ON) ухудшило качество движения в среднем на {abs((mean_tti_new - mean_tti_old)/mean_tti_old)*100:.1f}%.{C_RESET}")
        print("    Это объясняется тем, что без BPR (Bureau of Public Roads link performance function)\n"
              "    алгоритм поиска путей не учитывает текущую плотность и заторы ребер в достаточной мере,\n"
              "    направляя агентов на загруженные участки, что приводит к уплотнению черных зон.")
    else:
        print(f"  {C_GREEN}● Отключение BPR привело к неожиданному улучшению TTI на {abs((mean_tti_new - mean_tti_old)/mean_tti_old)*100:.1f}%.{C_RESET}")
        print("    Возможно, сильная пенализация BPR приводила к субоптимальным дальним объездам\n"
              "    и росту общего времени в пути (эффективность объездов снижалась).")
              
    if mean_queue_new < mean_queue_old:
        print(f"  {C_GREEN}● Очередь динамического перестроения (MPR) сократилась на {abs((mean_queue_new - mean_queue_old)/mean_queue_old)*100:.1f}%.{C_RESET}")
        print("    Это связано с меньшим числом срабатываний триггеров перерасчета маршрутов.")
    else:
        print(f"  {C_RED}● Нагрузка на очередь MPR выросла на {abs((mean_queue_new - mean_queue_old)/mean_queue_old)*100:.1f}%.{C_RESET}")
        print("    Это свидетельствует о резком возрастании числа агентов, требующих немедленного перестроения\n"
              "    из-за попадания в новые спонтанные заторы.")
              
    if mean_rps_new > mean_rps_old:
        print(f"  {C_GREEN}● Вычислительная скорость роутера выросла на {((mean_rps_new - mean_rps_old)/mean_rps_old)*100:.1f}%.{C_RESET}")
        print("    Без BPR-вычислений граф путей пересчитывается быстрее (упрощенная весовая функция),\n"
              "    что позволяет обслуживать больше RPS, однако качество прокладки маршрутов страдает.")
    else:
        print(f"  ● Изменение вычислительной скорости роутера незначительно ({((mean_rps_new - mean_rps_old)/mean_rps_old)*100:+.1f}%).")
        
    print("-" * 75)
    
    # Save the dashboard with unique half-hash name
    import re
    def extract_hash(filepath):
        basename = os.path.basename(filepath)
        match = re.match(r"run_([0-9a-fA-F]+)_", basename)
        if match:
            return match.group(1)
        return "unknown"

    hash_old = extract_hash(old_file)
    hash_new = extract_hash(new_file)
    
    half_old = hash_old[:4] if len(hash_old) >= 4 else hash_old
    half_new = hash_new[:4] if len(hash_new) >= 4 else hash_new
    
    comparison_name = f"comparison_{half_old}_{half_new}_dashboard.png"
    output_png = os.path.join(stats_dir, comparison_name)
    
    plot_comparison(output_png, time_old, time_new, data_old, data_new, 
                    overlap_times, old_overlap, new_overlap, t_start, t_end)
    
    print(f"{C_BOLD}{C_GREEN}Анализ сравнения выполнен успешно! График сохранен: {os.path.basename(output_png)}{C_RESET}")

if __name__ == "__main__":
    compare_runs()
