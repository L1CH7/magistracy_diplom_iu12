#!/usr/bin/env python3
import os
import csv
import sys
import glob

# Style settings
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

def plot_statistics(target_file, sim_time, tti, black_zones, red_zones, yellow_zones, 
                    router_rps, router_load, active_agents, waiting_reroute,
                    green_zones, visited_nodes, route_cycles,
                    waiting_spawn=None, route_time_max=None, route_time_avg=None, router_wait_time=None,
                    virtual_buffer=None, waiting_spillback=None):
    """Generate high-quality multi-panel scientific dashboard using matplotlib."""
    try:
        import matplotlib
        # Use Agg backend to allow running on headless systems / SSH
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print(f"\n{C_YELLOW}[!] Для построения графиков установите matplotlib: pip install matplotlib{C_RESET}")
        return

    print(f"{C_BOLD}{C_GREEN}Генерация графиков анализа симуляции...{C_RESET}")
    
    # Configure premium style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Liberation Sans']
    plt.rcParams['axes.edgecolor'] = '#cccccc'
    plt.rcParams['axes.linewidth'] = 0.8
    
    # 3x2 grid dashboard
    fig, axs = plt.subplots(3, 2, figsize=(15, 15), dpi=150)
    fig.suptitle(f"Панель Анализа Симуляции: {os.path.basename(target_file)}", fontsize=16, fontweight='bold', y=0.98)
    
    # 1. Travel Time Index (TTI) Over Time
    axs[0, 0].plot(sim_time, tti, color='#1f77b4', linewidth=2.0, label='TTI (Индекс Задержки)')
    axs[0, 0].axhline(1.0, color='r', linestyle='--', linewidth=0.8, alpha=0.7, label='Порог Free-Flow (1.0)')
    axs[0, 0].set_title("Динамика Индекса Задержки (TTI)", fontsize=12, fontweight='bold')
    axs[0, 0].set_xlabel("Время симуляции (сек)", fontsize=10)
    axs[0, 0].set_ylabel("Коэффициент TTI", fontsize=10)
    axs[0, 0].grid(True, linestyle=':', alpha=0.6)
    axs[0, 0].legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none')
    
    # 2. Congestion Zones Breakdown (Yellow/Red/Black)
    axs[0, 1].plot(sim_time, black_zones, color='#800080', linewidth=1.8, label='Черные зоны (Затор >= 2x)')
    axs[0, 1].plot(sim_time, red_zones, color='#d62728', linewidth=1.8, label='Красные зоны (Перегрузка >= 1x)')
    axs[0, 1].plot(sim_time, yellow_zones, color='#bcbd22', linewidth=1.5, label='Желтые зоны (Плотный >= 0.3x)')
    axs[0, 1].set_title("Заторы и Перегрузка Дорожной Сети", fontsize=12, fontweight='bold')
    axs[0, 1].set_xlabel("Время симуляции (сек)", fontsize=10)
    axs[0, 1].set_ylabel("Количество ребер", fontsize=10)
    axs[0, 1].grid(True, linestyle=':', alpha=0.6)
    axs[0, 1].legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none')
    
    # 3. Router Performance (RPS & Load)
    ax3_left = axs[1, 0]
    ax3_right = ax3_left.twinx()
    
    line1 = ax3_left.plot(sim_time, router_rps, color='#2ca02c', linewidth=1.5, label='Скорость ALT (RPS)')
    # Convert load fraction to percentage
    router_load_pct = [load * 100.0 for load in router_load]
    line2 = ax3_right.plot(sim_time, router_load_pct, color='#ff7f0e', linewidth=1.5, linestyle='--', label='Нагрузка потока (%)')
    
    ax3_left.set_title("Производительность Вычислений Роутера", fontsize=12, fontweight='bold')
    ax3_left.set_xlabel("Время симуляции (сек)", fontsize=10)
    ax3_left.set_ylabel("Вычисленные маршруты / сек (RPS)", fontsize=10)
    ax3_right.set_ylabel("Загрузка потока роутера (%)", fontsize=10)
    ax3_left.grid(True, linestyle=':', alpha=0.6)
    
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax3_left.legend(lines, labels, loc='upper left', frameon=True, facecolor='white', edgecolor='none')
    
    # 4. Population and Queue Size
    axs[1, 1].plot(sim_time, active_agents, color='#17becf', linewidth=1.8, label='Активные на дорогах')
    axs[1, 1].plot(sim_time, waiting_reroute, color='#ff7f0e', linewidth=1.5, label='Очередь MPR (Живые)')
    if waiting_spawn is not None and any(waiting_spawn):
        axs[1, 1].plot(sim_time, waiting_spawn, color='#9467bd', linewidth=1.5, linestyle='--', label='Очередь Spawn (Призраки)')
    if virtual_buffer is not None and any(virtual_buffer):
        axs[1, 1].plot(sim_time, virtual_buffer, color='#e377c2', linewidth=1.5, linestyle=':', label='Виртуальный буфер SUMO (2 м/с)')
    if waiting_spillback is not None and any(waiting_spillback):
        axs[1, 1].plot(sim_time, waiting_spillback, color='#d62728', linewidth=1.5, linestyle='-.', label='Застряли (0 км/ч)')
    axs[1, 1].set_title("Популяция Агентов и Очереди Роутера", fontsize=12, fontweight='bold')
    axs[1, 1].set_xlabel("Время симуляции (сек)", fontsize=10)
    axs[1, 1].set_ylabel("Количество агентов", fontsize=10)
    axs[1, 1].grid(True, linestyle=':', alpha=0.6)
    axs[1, 1].legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none')

    # 5. Free-Flow Roads (Green Zones) - separate plot so they don't blot out other zones
    axs[2, 0].plot(sim_time, green_zones, color='#2ca02c', linewidth=2.0, label='Зеленые зоны (Свободно < 0.3x)')
    axs[2, 0].set_title("Свободные дороги дорожной сети", fontsize=12, fontweight='bold')
    axs[2, 0].set_xlabel("Время симуляции (сек)", fontsize=10)
    axs[2, 0].set_ylabel("Количество ребер", fontsize=10)
    axs[2, 0].grid(True, linestyle=':', alpha=0.6)
    axs[2, 0].legend(loc='upper left', frameon=True, facecolor='white', edgecolor='none')

    # 6. A* Search Space & CPU Cycles / Wall-clock times (Double Y-Axis)
    ax6_left = axs[2, 1]
    ax6_right = ax6_left.twinx()
    
    line1_prof = ax6_left.plot(sim_time, visited_nodes, color='#1f77b4', linewidth=1.8, label='Посещенные вершины (ед)')
    
    lines_prof = line1_prof
    if route_time_max is not None and any(route_time_max) and sum(route_time_max) > 0:
        max_ms = [t / 1000.0 for t in route_time_max]
        avg_ms = [t / 1000.0 for t in route_time_avg]
        line2_prof = ax6_right.plot(sim_time, max_ms, color='#d62728', linewidth=1.5, label='Время A* Max (мс)')
        line3_prof = ax6_right.plot(sim_time, avg_ms, color='#2ca02c', linewidth=1.2, linestyle='--', label='Время A* Avg (мс)')
        ax6_right.set_ylabel("Время расчета пути (мс)", fontsize=10)
        lines_prof += line2_prof + line3_prof
    else:
        cycles_m = [c / 1e6 for c in route_cycles]
        line2_prof = ax6_right.plot(sim_time, cycles_m, color='#9467bd', linewidth=1.5, linestyle=':', label='Такты CPU (млн)')
        ax6_right.set_ylabel("Миллионы тактов CPU (RDTSC)", fontsize=10)
        lines_prof += line2_prof
        
    ax6_left.set_title("Диагностика поиска пути A*", fontsize=12, fontweight='bold')
    ax6_left.set_xlabel("Время симуляции (сек)", fontsize=10)
    ax6_left.set_ylabel("Посещенные вершины (ед)", fontsize=10)
    ax6_left.grid(True, linestyle=':', alpha=0.6)
    
    labels_prof = [l.get_label() for l in lines_prof]
    ax6_left.legend(lines_prof, labels_prof, loc='upper left', frameon=True, facecolor='white', edgecolor='none')
    
    # Adjust layout
    plt.tight_layout()
    
    # Save to PNG
    output_png = target_file.replace(".csv", "_dashboard.png")
    plt.savefig(output_png, bbox_inches='tight')
    plt.close()
    
    print(f"{C_BOLD}{C_GREEN}[+] График успешно сохранен: {os.path.basename(output_png)}{C_RESET}")

def analyze_latest():
    stats_dir = os.path.dirname(os.path.abspath(__file__))
    
    # If a specific file is provided as argument, use it
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
        if not os.path.isabs(target_file):
            target_file = os.path.join(stats_dir, target_file)
    else:
        # Find latest CSV
        csv_files = glob.glob(os.path.join(stats_dir, "*.csv"))
        if not csv_files:
            print(f"{C_RED}Ошибка: CSV файлы телеметрии не найдены в {stats_dir}!{C_RESET}")
            sys.exit(1)
        target_file = max(csv_files, key=os.path.getmtime)
        
    basename = os.path.basename(target_file)
    bpr_status = "Неизвестно"
    prof_status = "Неизвестно"
    if "bpr_on" in basename or "BUCKETS_ON" in basename:
        bpr_status = f"{C_GREEN}Включен (ON){C_RESET}"
    elif "bpr_off" in basename or "BUCKETS_OFF" in basename:
        bpr_status = f"{C_RED}Отключен (OFF) [Статическая маршрутизация]{C_RESET}"
        
    if "prof_on" in basename or "PROFILE_ON" in basename:
        prof_status = f"{C_GREEN}Включен (ON) [Сбор метрик поиска]{C_RESET}"
    elif "prof_off" in basename or "PROFILE_OFF" in basename:
        prof_status = f"{C_RED}Отключен (OFF){C_RESET}"
        
    print(f"{C_BOLD}{C_CYAN}=== НАУЧНО-АНАЛИТИЧЕСКИЙ ОТЧЕТ ТРАНСПОРТНОЙ СИМУЛЯЦИИ ==={C_RESET}")
    print(f"Файл данных:  {basename}")
    print(f"Режим BPR:    {bpr_status}")
    print(f"Профайлинг:   {prof_status}")
    print("-" * 70)
    
    # Read rows
    sim_time = []
    tti = []
    active_agents = []
    waiting_reroute = []
    completed_trips = []
    dynamic_reroutes = []
    black_zones = []
    red_zones = []
    yellow_zones = []
    router_rps = []
    saved_duplicates = []
    router_load = []
    green_zones = []
    visited_nodes = []
    route_cycles = []
    waiting_spawn = []
    route_time_max = []
    route_time_avg = []
    router_wait_time = []
    
    virtual_buffer = []
    waiting_spillback = []
    
    with open(target_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sim_time.append(float(row["SimTime"]))
            tti.append(float(row["TTI"]))
            active_agents.append(int(row["ActiveAgents"]))
            waiting_reroute.append(int(row["WaitingReroute"]))
            completed_trips.append(int(row["CompletedTrips"]))
            dynamic_reroutes.append(int(row["DynamicReroutes"]))
            black_zones.append(int(row["BlackZones"]))
            red_zones.append(int(row["RedZones"]))
            yellow_zones.append(int(row["YellowZones"]))
            router_rps.append(float(row["RouterRPS"]))
            saved_duplicates.append(int(row["SavedDuplicates"]))
            router_load.append(float(row["RouterLoad"]))
            green_zones.append(int(row.get("GreenZones", 0)))
            visited_nodes.append(float(row.get("VisitedNodes", 0.0)))
            route_cycles.append(float(row.get("RouteCycles", 0.0)))
            waiting_spawn.append(int(row.get("WaitingSpawn", 0)))
            route_time_max.append(float(row.get("RouteTimeMaxUs", 0.0)))
            route_time_avg.append(float(row.get("RouteTimeAvgUs", 0.0)))
            router_wait_time.append(float(row.get("RouterWaitTimeUs", 0.0)))
            virtual_buffer.append(int(row.get("VirtualBuffer", 0)))
            waiting_spillback.append(int(row.get("WaitingSpillbackQueue", 0)))
            
    n_samples = len(sim_time)
    if n_samples < 2:
        print(f"{C_YELLOW}Предупреждение: Недостаточно данных для полного анализа ({n_samples} записей).{C_RESET}")
        sys.exit(0)
        
    # Stats calculations
    run_duration = sim_time[-1] - sim_time[0]
    avg_tti = sum(tti) / n_samples
    min_tti = min(tti)
    max_tti = max(tti)
    
    peak_black = max(black_zones)
    peak_red = max(red_zones)
    peak_yellow = max(yellow_zones)
    
    total_completed = completed_trips[-1] - completed_trips[0]
    total_reroutes = dynamic_reroutes[-1] - dynamic_reroutes[0]
    
    avg_load = (sum(router_load) / n_samples) * 100.0
    peak_rps = max(router_rps)
    avg_rps = sum(router_rps) / n_samples
    
    total_saved = saved_duplicates[-1] - saved_duplicates[0]
    
    # Correlations
    corr_tti_black = pearson_correlation(tti, black_zones)
    corr_tti_red = pearson_correlation(tti, red_zones)
    corr_tti_reroute = pearson_correlation(tti, waiting_reroute)
    
    # Output metrics
    print(f"{C_BOLD}Общие параметры запуска:{C_RESET}")
    print(f"  ├─ Длительность замера:       {C_BOLD}{run_duration:.1f} сек.{C_RESET} симуляции (от {sim_time[0]:.1f} до {sim_time[-1]:.1f})")
    print(f"  ├─ Записей телеметрии:        {n_samples} точек")
    print(f"  ├─ Успешно доехали (авто):    {total_completed} завершенных поездок")
    print(f"  └─ Сделано объездов MPR:      {total_reroutes} перестроений")
    print("")
    
    print(f"{C_BOLD}Метрики задержки (TTI — Travel Time Index):{C_RESET}")
    print(f"  ├─ Минимальный TTI:           {C_GREEN}{min_tti:.4f}{C_RESET} (свободное движение)")
    print(f"  ├─ Максимальный TTI:          {C_RED if max_tti >= 1.0 else C_YELLOW}{max_tti:.4f}{C_RESET} (пик заторов)")
    print(f"  ├─ Средний TTI:               {C_CYAN}{avg_tti:.4f}{C_RESET}")
    print(f"  └─ Динамика TTI:              {C_YELLOW}{tti[0]:.4f}{C_RESET} → {C_MAGENTA}{tti[-1]:.4f}{C_RESET} (прирост: {(tti[-1]-tti[0])*100:+.1f}%)")
    print("")
    
    print(f"{C_BOLD}Анализ дорожной сети и заторов:{C_RESET}")
    print(f"  ├─ Пик черных зон (затор):    {C_MAGENTA}{peak_black}{C_RESET} ребер")
    print(f"  ├─ Пик красных зон (нагрузка): {C_RED}{peak_red}{C_RESET} ребер")
    print(f"  └─ Пик желтых зон (плотность): {C_YELLOW}{peak_yellow}{C_RESET} ребер")
    print("")
    
    print(f"{C_BOLD}Производительность роутера и сбережение ресурсов:{C_RESET}")
    print(f"  ├─ Пиковая скорость ALT:  {C_CYAN}{peak_rps:.1f}{C_RESET} RPS")
    print(f"  ├─ Средняя скорость ALT: {C_CYAN}{avg_rps:.1f}{C_RESET} RPS")
    print(f"  ├─ Средняя нагрузка потока:   {C_YELLOW}{avg_load:.1f}%{C_RESET}")
    print(f"  ├─ Сэкономлено ALT-задач: {C_GREEN}{total_saved}{C_RESET} (предотвращено дубликатов за запуск)")
    if any(route_time_max):
        print(f"  ├─ Пиковое время поиска: {C_RED}{max(route_time_max)/1000:.2f} мс{C_RESET}")
        print(f"  ├─ Среднее время поиска: {C_YELLOW}{sum(route_time_avg)/len(route_time_avg)/1000:.2f} мс{C_RESET}")
        print(f"  └─ Макс. простой WaitForAll: {C_MAGENTA}{max(router_wait_time)/1e6:.2f} сек.{C_RESET}")
    else:
        print(f"  └─ Дополнительная профайлинг-телеметрия не обнаружена (профайлинг отключен)")
    print("")
    
    print(f"{C_BOLD}Корреляционный анализ (Pearson r):{C_RESET}")
    print(f"  ├─ Корреляция TTI ↔ Черные зоны:  {C_BOLD}{corr_tti_black:+.4f}{C_RESET}", end="")
    if abs(corr_tti_black) >= 0.7:
        print(f" {C_RED}(Сильная прямая зависимость: заторы напрямую задерживают поездки){C_RESET}")
    else:
        print(f" {C_YELLOW}(Умеренная зависимость){C_RESET}")
        
    print(f"  ├─ Корреляция TTI ↔ Красные зоны:  {C_BOLD}{corr_tti_red:+.4f}{C_RESET}")
    print(f"  └─ Корреляция TTI ↔ Очередь MPR:   {C_BOLD}{corr_tti_reroute:+.4f}{C_RESET}", end="")
    if corr_tti_reroute >= 0.5:
        print(f" {C_YELLOW}(Рост пробок увеличивает нагрузку на очереди МПР){C_RESET}")
    else:
        print("")
        
    print("-" * 70)
    
    # Generate matplotlib visual plots
    plot_statistics(target_file, sim_time, tti, black_zones, red_zones, yellow_zones, 
                    router_rps, router_load, active_agents, waiting_reroute,
                    green_zones, visited_nodes, route_cycles,
                    waiting_spawn, route_time_max, route_time_avg, router_wait_time,
                    virtual_buffer, waiting_spillback)
    
    print(f"{C_GREEN}Анализ завершен успешно! Данные готовы для использования в научной работе.{C_RESET}")

if __name__ == "__main__":
    analyze_latest()
