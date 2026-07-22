#!/usr/bin/env python3
import asyncio
import json
import sys
import os
import time
import csv
import hashlib
import http.client
from urllib.parse import urlparse
import websockets
from typing import Dict, Any, List

# API Configurations
STATS_URL = "http://localhost:8000/api/v1/sim/stats"
WS_URL = "ws://localhost:8000/ws/sim_telemetry"

# Colors for terminal styling
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_BG_RED = "\033[41m\033[37m"
C_BG_BLACK = "\033[40m\033[97m"

def fetch_stats() -> Dict[str, Any]:
    """Fetch global simulation stats using standard library to avoid external dependencies."""
    try:
        url = urlparse(STATS_URL)
        conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=1.5)
        conn.request("GET", url.path)
        resp = conn.getresponse()
        if resp.status == 200:
            raw_data = resp.read().decode('utf-8')
            parsed = json.loads(raw_data)
            if parsed.get("status") == "success":
                return parsed.get("data", {})
        conn.close()
    except Exception:
        pass
    return {}

def make_bar(percent: float, width: int = 20, color_code: str = C_GREEN) -> str:
    """Create a colored text-based progress bar."""
    filled = int(round(percent * width))
    empty = width - filled
    bar_str = "█" * filled + "░" * empty
    return f"{color_code}[{bar_str}]{C_RESET}"

async def monitor():
    print(f"{C_BOLD}{C_CYAN}Инициализация системы мониторинга черных зон...{C_RESET}")
    print(f"Подключение к WebSocket: {WS_URL}...")

    has_started = False
    last_seen_sim_time = 0.0
    stats_cache = {}
    
    last_rps_time = time.time()
    last_actual_calculated = None
    current_rps = 0.0
    
    # Prepare unique CSV run file in scripts/stats/
    stats_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats")
    os.makedirs(stats_dir, exist_ok=True)
    
    # Try fetching initial stats synchronously to dynamically discover compile-time/run-time parameters
    print(f"{C_BOLD}{C_CYAN}Получение конфигурации от демона...{C_RESET}")
    initial_stats = {}
    for _ in range(10):
        initial_stats = fetch_stats()
        if initial_stats:
            break
        time.sleep(0.5)
        
    num_buckets = initial_stats.get("num_buckets", 24)
    slot_sec = initial_stats.get("slot_sec", 300)
    configured_agents = initial_stats.get("configured_agents", 200000)
    asf = initial_stats.get("asf", 1)
    bpr_enabled = initial_stats.get("bpr_enabled", False)
    profiling_enabled = initial_stats.get("profiling_enabled", False)
    
    bpr_status = "on" if bpr_enabled else "off"
    prof_status = "on" if profiling_enabled else "off"
    
    stats_cache = initial_stats if initial_stats else {}
    
    run_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    csv_filename = os.path.join(
        stats_dir, 
        f"run_{run_hash}_bpr_{bpr_status}_prof_{prof_status}_{num_buckets}b_{slot_sec}s_{configured_agents}a_{asf}asf.csv"
    )
    last_logged_sim_time = -100.0
    
    print(f"{C_BOLD}{C_GREEN}[+] Файл телеметрии: {os.path.basename(csv_filename)}{C_RESET}")
    
    csv_headers = [
        "SimTime", "TTI", "ActiveAgents", "WaitingReroute", 
        "CompletedTrips", "DynamicReroutes", "BlackZones", 
        "RedZones", "YellowZones", "RouterRPS", "SavedDuplicates", "RouterLoad",
        "GreenZones", "VisitedNodes", "RouteCycles",
        "WaitingSpawn", "RouteTimeMaxUs", "RouteTimeAvgUs", "RouterWaitTimeUs",
        "VirtualBuffer", "WaitingSpillbackQueue"
    ]
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)
    
    # Background task to poll stats periodically
    async def poll_stats_loop():
        nonlocal stats_cache
        while True:
            fetched = fetch_stats()
            if fetched:
                stats_cache = fetched
            await asyncio.sleep(1.0)

    poll_task = asyncio.create_task(poll_stats_loop())

    try:
        # Increase max_size to None to allow huge frames containing 65k+ active edges (3.5MB+ JSON payloads)
        async with websockets.connect(WS_URL, max_size=None) as ws:
            while True:
                message = await ws.recv()
                try:
                    entries = json.loads(message)
                except Exception:
                    continue

                if not isinstance(entries, list):
                    continue

                # Analysis variables
                total_active_edges = len(entries)
                black_edges = []
                red_edges = []
                yellow_edges = []
                green_edges = []
                
                max_ratio = 0.0
                sum_ratio = 0.0

                for entry in entries:
                    edge_id = entry.get("id")
                    v = entry.get("v", 0)  # Encoded ratio * 1000
                    ratio = v / 1000.0

                    if ratio > max_ratio:
                        max_ratio = ratio
                    sum_ratio += ratio

                    item = {"id": edge_id, "ratio": ratio}
                    if ratio >= 2.0:
                        black_edges.append(item)
                    elif ratio >= 1.0:
                        red_edges.append(item)
                    elif ratio >= 0.3:
                        yellow_edges.append(item)
                    else:
                        green_edges.append(item)

                # Sort by congestion ratio to identify major bottlenecks
                all_edges = black_edges + red_edges + yellow_edges + green_edges
                all_edges.sort(key=lambda x: x["ratio"], reverse=True)
                top_bottlenecks = all_edges[:10]

                # Compute statistics
                p_black = (len(black_edges) / total_active_edges * 100) if total_active_edges > 0 else 0.0
                p_red = (len(red_edges) / total_active_edges * 100) if total_active_edges > 0 else 0.0
                p_yellow = (len(yellow_edges) / total_active_edges * 100) if total_active_edges > 0 else 0.0
                p_green = (len(green_edges) / total_active_edges * 100) if total_active_edges > 0 else 0.0
                avg_overload = (sum_ratio / total_active_edges) if total_active_edges > 0 else 0.0

                # Read cached global stats
                sim_time = stats_cache.get("sim_time", 0.0)
                active_agents = stats_cache.get("active_agents", 0)

                # State change detection (start / stop / restart)
                if not has_started:
                    if sim_time > 0.5 or active_agents > 0:
                        has_started = True
                else:
                    if sim_time < last_seen_sim_time - 1.0 or (sim_time == 0.0 and active_agents == 0):
                        # Reset or stop was detected!
                        await asyncio.sleep(1.0)
                        new_stats = fetch_stats()
                        new_sim_time = new_stats.get("sim_time", 0.0)
                        new_active = new_stats.get("active_agents", 0)
                        if new_sim_time > 0.0 or new_active > 0:
                            print(f"\n{C_BOLD}{C_YELLOW}[!] Обнаружен перезапуск симуляции. Завершаем текущую сессию.{C_RESET}")
                            return "restart"
                        else:
                            print(f"\n{C_BOLD}{C_RED}[!] Симуляция остановлена. Завершаем мониторинг.{C_RESET}")
                            return "stop"
                
                last_seen_sim_time = sim_time
                config_agents = stats_cache.get("configured_agents", 0)
                asf = stats_cache.get("asf", 1)
                total_spawns = stats_cache.get("total_spawns", 0)
                reroutes = stats_cache.get("reroutes", 0)
                tti = stats_cache.get("tti_global", 0.0)
                routes_completed = stats_cache.get("routes_completed", 0)
                routes_failed = stats_cache.get("routes_failed", 0)

                routes_computed = stats_cache.get("routes_computed", 0)
                routes_successful = stats_cache.get("routes_successful", 0)
                routes_discarded = stats_cache.get("routes_discarded", 0)
                routes_stale = stats_cache.get("routes_stale", 0)
                router_load = stats_cache.get("router_load", 0.0)

                # Real-time actual pathfinding RPS tracking with Exponential Moving Average (EMA)
                actual_calculated = routes_successful + routes_discarded + routes_failed
                curr_real_time = time.time()
                dt_real = curr_real_time - last_rps_time
                if dt_real >= 0.5:
                    if sim_time < 30.0 or last_actual_calculated is None or last_actual_calculated == 0:
                        # Reset baseline during initial warm-up / spawning wave to ignore spawning burst
                        last_actual_calculated = actual_calculated
                        instant_rps = 0.0
                        current_rps = 0.0
                    else:
                        instant_rps = (actual_calculated - last_actual_calculated) / dt_real
                        last_actual_calculated = actual_calculated

                    # Smooth with EMA: alpha = 0.2 (averages over roughly 5 seconds / 10 samples)
                    if sim_time >= 30.0:
                        if current_rps == 0.0 and instant_rps > 0.0:
                            current_rps = instant_rps
                        elif instant_rps > 0.0 or current_rps > 0.0:
                            alpha = 0.2
                            current_rps = alpha * instant_rps + (1.0 - alpha) * current_rps
                    
                    last_rps_time = curr_real_time

                agents_driving = stats_cache.get("agents_driving", 0)
                agents_rerouting = stats_cache.get("agents_rerouting", 0)
                agents_waiting_spawn = stats_cache.get("agents_waiting_spawn", 0)
                agents_idle = stats_cache.get("agents_idle", 0)
                virtual_buffer = stats_cache.get("virtual_buffer_count", 0)

                sum_agents = agents_driving + agents_rerouting + agents_waiting_spawn + agents_idle + virtual_buffer
                active_on_roads = agents_driving + agents_rerouting + virtual_buffer
                inactive_agents = agents_waiting_spawn + agents_idle

                total_cars = active_on_roads * asf
                stuck_cars_est = int(total_cars * (p_black / 100.0))

                visited_nodes = stats_cache.get("visited_nodes_avg", 0.0)
                route_cycles = stats_cache.get("route_cycles_avg", 0.0)
                route_time_max = stats_cache.get("route_time_max_us", 0)
                route_time_avg = stats_cache.get("route_time_avg_us", 0.0)
                router_wait_time = stats_cache.get("router_wait_time_us", 0)

                # Log stats to CSV if simulation time progressed by at least 1.0s
                if sim_time - last_logged_sim_time >= 1.0:
                    with open(csv_filename, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            round(sim_time, 1),
                            round(tti, 4),
                            active_on_roads,
                            agents_rerouting,
                            routes_completed,
                            reroutes,
                            len(black_edges),
                            len(red_edges),
                            len(yellow_edges),
                            round(current_rps, 1),
                            routes_stale,
                            round(router_load, 4),
                            len(green_edges),
                            round(visited_nodes, 2),
                            round(route_cycles, 2),
                            agents_waiting_spawn,
                            route_time_max,
                            round(route_time_avg, 2),
                            router_wait_time,
                            virtual_buffer,
                            stats_cache.get("waiting_in_queue_count", 0)
                        ])
                    last_logged_sim_time = sim_time

                # Build output screen
                out = []
                out.append("\033[H\033[J") # Clear screen & home cursor
                out.append(f"{C_BOLD}{C_BG_BLACK}  TRAFFIC SIMULATION DIAGNOSTICS & BOTTLENECK MONITOR  {C_RESET}")
                out.append(f"Время симуляции: {C_BOLD}{sim_time:.1f} сек.{C_RESET} | Индекс задержки (TTI): {C_BOLD}{C_CYAN}{tti:.2f}{C_RESET}")
                out.append("")
                out.append(f"МАРШРУТЫ И РОУТЕР:")
                out.append(f"  ├─ Производительность:     {C_CYAN}{current_rps:.1f}{C_RESET} RPS | Нагрузка потока: {C_YELLOW}{router_load*100:.1f}%{C_RESET}")
                if visited_nodes > 0 or route_cycles > 0:
                    out.append(f"  ├─ Профайлер A*:            {C_CYAN}{visited_nodes:.1f}{C_RESET} вершин | {C_GREEN}{route_cycles/1e6:.2f}M{C_RESET} тактов CPU")
                out.append(f"  ├─ Время поиска (Max/Avg): {C_RED}{route_time_max/1000:.2f}ms{C_RESET} / {C_YELLOW}{route_time_avg/1000:.2f}ms{C_RESET}")
                out.append(f"  ├─ Ожидание WaitForAll:    {C_MAGENTA}{router_wait_time/1e6:.2f}s{C_RESET}")
                out.append(f"  ├─ Обработано запросов:    {C_BOLD}{routes_computed}{C_RESET}")
                out.append(f"  │   ├─ Успешно построено:  {C_GREEN}{routes_successful}{C_RESET} (выездов: {total_spawns})")
                out.append(f"  │   ├─ Отклонено (сдвиг):  {C_YELLOW}{routes_discarded}{C_RESET} (агент сместился)")
                out.append(f"  │   ├─ Сэкономлено (stale): {C_GREEN}{routes_stale}{C_RESET} (сброшено дубликатов)")
                out.append(f"  │   └─ Ошибок поиска пути: {C_RED}{routes_failed}{C_RESET}")
                out.append(f"  ├─ Успешно прибыло (доехали): {C_GREEN}{routes_completed}{C_RESET} авто")
                out.append(f"  └─ Динамических объездов MPR: {C_YELLOW}{reroutes}{C_RESET}")
                out.append("")
                spillback_queue_cnt = stats_cache.get("waiting_in_queue_count", 0)
                out.append(f"РАСПРЕДЕЛЕНИЕ АГЕНТОВ (Всего в симуляции: {C_BOLD}{config_agents}{C_RESET}):")
                out.append(f"  ├─ {C_BOLD}Активные на дорогах:{C_RESET}   {C_BOLD}{active_on_roads}{C_RESET}")
                out.append(f"  │   ├─ Едут по маршруту:  {C_GREEN}{agents_driving}{C_RESET} авто")
                out.append(f"  │   ├─ Ищут объезд затора: {C_YELLOW}{agents_rerouting}{C_RESET} авто (в очереди роутера)")
                out.append(f"  │   ├─ Виртуальный буфер:  {C_MAGENTA}{virtual_buffer}{C_RESET} авто (SUMO 2 м/с)")
                out.append(f"  │   └─ Застряли (0 км/ч):  {C_RED}{spillback_queue_cnt}{C_RESET} авто (на границе ребра)")
                out.append(f"  └─ {C_BOLD}Неактивные в буфере:{C_RESET}   {C_BOLD}{inactive_agents}{C_RESET}")
                out.append(f"      ├─ В очереди на выезд: {C_CYAN}{agents_waiting_spawn}{C_RESET} авто (ждут первый маршрут)")
                out.append(f"      └─ Ожидают новый цикл: {C_MAGENTA}{agents_idle}{C_RESET} авто (завершили поездку)")
                
                pct = (sum_agents / config_agents * 100.0) if config_agents > 0 else 0.0
                status_ok = f"{C_GREEN}[OK: {pct:.1f}%]{C_RESET}" if sum_agents == config_agents else f"{C_RED}[НЕСООТВЕТСТВИЕ: {pct:.1f}%]{C_RESET}"
                out.append("")
                out.append(f"Итоговый баланс популяции: {C_BOLD}{sum_agents}/{config_agents}{C_RESET} {status_ok}")
                out.append("--------------------------------------------------------------------------------")
                
                out.append(f"{C_BOLD}АНАЛИЗ ДОРОЖНОЙ СЕТИ (Активных ребер с трафиком: {total_active_edges}){C_RESET}")
                
                # Distribution list
                out.append(f"  {C_BOLD}{C_MAGENTA}ЧЕРНЫЕ ЗОНЫ (Затор >= 2.0x):{C_RESET}      {len(black_edges):5d} ({p_black:5.1f}%) {make_bar(p_black/100, 20, C_MAGENTA)} -> {C_BOLD}{C_RED}~{stuck_cars_est} авто застряло{C_RESET}")
                out.append(f"  {C_BOLD}{C_RED}КРАСНЫЕ ЗОНЫ (Перегрузка >= 1.0x):{C_RESET}  {len(red_edges):5d} ({p_red:5.1f}%) {make_bar(p_red/100, 20, C_RED)}")
                out.append(f"  {C_BOLD}{C_YELLOW}ЖЕЛТЫЕ ЗОНЫ (Плотный трафик >= 0.3x):{C_RESET}{len(yellow_edges):5d} ({p_yellow:5.1f}%) {make_bar(p_yellow/100, 20, C_YELLOW)}")
                out.append(f"  {C_BOLD}{C_GREEN}ЗЕЛЕНЫЕ ЗОНЫ (Свободно < 0.3x):{C_RESET}     {len(green_edges):5d} ({p_green:5.1f}%) {make_bar(p_green/100, 20, C_GREEN)}")
                
                out.append("")
                out.append(f"Средний коэффициент затора (Network-wide): {C_BOLD}{avg_overload:.3f}{C_RESET}")
                out.append(f"Пиковый коэффициент затора (Worst edge):    {C_BOLD}{C_BG_RED if max_ratio >= 2.0 else C_RED} {max_ratio:.2f}x {C_RESET}")
                out.append("--------------------------------------------------------------------------------")
                
                out.append(f"{C_BOLD}ТОП-10 КРИТИЧЕСКИХ УЗЛОВ (OSM WAY ID & НАГРУЗКА){C_RESET}")
                out.append(f"  {'#':2s} | {'OSM Way ID':15s} | {'Коэффициент':12s} | {'Статус':20s} | {'Эст. Скорость':15s}")
                out.append(f"  {'-'*75}")
                
                for idx, edge in enumerate(top_bottlenecks, 1):
                    r = edge["ratio"]
                    eid = edge["id"]
                    
                    if r >= 2.0:
                        status = f"{C_BOLD}{C_MAGENTA}ЧЕРНАЯ ЗОНА (Затор){C_RESET}"
                        speed = f"{C_BOLD}{C_RED}0 км/ч (Стоит){C_RESET}"
                    elif r >= 1.0:
                        status = f"{C_RED}КРАСНАЯ ЗОНА{C_RESET}"
                        speed = f"{C_YELLOW}~5 - 12 км/ч{C_RESET}"
                    elif r >= 0.5:
                        status = f"{C_YELLOW}ЖЕЛТАЯ ЗОНА{C_RESET}"
                        speed = f"{C_GREEN}~20 - 40 км/ч{C_RESET}"
                    else:
                        status = f"{C_GREEN}ЗЕЛЕНАЯ ЗОНА{C_RESET}"
                        speed = f"{C_GREEN}> 60 км/ч{C_RESET}"
                        
                    out.append(f"  {idx:2d} | {eid:15d} | {r:10.2f}x | {status:30s} | {speed}")
                
                out.append("--------------------------------------------------------------------------------")
                out.append(f"{C_YELLOW}Выход: Ctrl+C{C_RESET}")

                sys.stdout.write("\n".join(out))
                sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

async def main_runner():
    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        while True:
            res = await monitor()
            if res == "restart":
                print(f"\n{C_BOLD}{C_CYAN}[+] Начинаем новый цикл мониторинга...{C_RESET}\n")
                await asyncio.sleep(1.0)
                continue
            else:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor back
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
        print(f"\n{C_BOLD}Мониторинг завершен.{C_RESET}")

if __name__ == "__main__":
    try:
        asyncio.run(main_runner())
    except KeyboardInterrupt:
        print("\nВыход...")
