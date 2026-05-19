#!/usr/bin/env python3
import asyncio
import json
import sys
import os
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
    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    print(f"{C_BOLD}{C_CYAN}Инициализация системы мониторинга черных зон...{C_RESET}")
    print(f"Подключение к WebSocket: {WS_URL}...")

    stats_cache = {}
    
    # Background task to poll stats periodically
    async def poll_stats_loop():
        nonlocal stats_cache
        while True:
            fetched = fetch_stats()
            if fetched:
                stats_cache = fetched
            await asyncio.sleep(1.0)

    asyncio.create_task(poll_stats_loop())

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
                config_agents = stats_cache.get("configured_agents", 0)
                asf = stats_cache.get("asf", 1)
                total_spawns = stats_cache.get("total_spawns", 0)
                reroutes = stats_cache.get("reroutes", 0)
                tti = stats_cache.get("tti_global", 0.0)
                routes_completed = stats_cache.get("routes_completed", 0)
                routes_failed = stats_cache.get("routes_failed", 0)

                total_cars = active_agents * asf
                stuck_cars_est = int(total_cars * (p_black / 100.0))

                # Build output screen
                out = []
                out.append("\033[H\033[J") # Clear screen & home cursor
                out.append(f"{C_BOLD}{C_BG_BLACK}  TRAFFIC SIMULATION DIAGNOSTICS & BOTTLENECK MONITOR  {C_RESET}")
                out.append(f"Время симуляции: {C_BOLD}{sim_time:.1f} сек.{C_RESET} | TTI: {C_BOLD}{C_CYAN}{tti:.2f}{C_RESET}")
                out.append(f"Активно агентов: {C_BOLD}{active_agents}/{config_agents}{C_RESET} (ASF: {asf} -> {C_BOLD}{total_cars}{C_RESET} вирт. авто)")
                out.append(f"Спавны: {C_BOLD}{total_spawns}{C_RESET} | Рероуты MPR: {C_BOLD}{C_YELLOW}{reroutes}{C_RESET} | Успешно/Застряло: {C_GREEN}{routes_completed}{C_RESET}/{C_RED}{routes_failed}{C_RESET}")
                out.append("--------------------------------------------------------------------------------")
                
                out.append(f"{C_BOLD}АНАЛИЗ ДОРОЖНОЙ СЕТИ (Активных ребер с трафиком: {total_active_edges}){C_RESET}")
                
                # Distribution list
                out.append(f"  {C_BOLD}{C_MAGENTA}ЧЕРНЫЕ ЗОНЫ (Spillback >= 2.0x):{C_RESET}  {len(black_edges):5d} ({p_black:5.1f}%) {make_bar(p_black/100, 20, C_MAGENTA)} -> {C_BOLD}{C_RED}~{stuck_cars_est} авто застряло{C_RESET}")
                out.append(f"  {C_BOLD}{C_RED}КРАСНЫЕ ЗОНЫ (Congested >= 1.0x):{C_RESET} {len(red_edges):5d} ({p_red:5.1f}%) {make_bar(p_red/100, 20, C_RED)}")
                out.append(f"  {C_BOLD}{C_YELLOW}ЖЕЛТЫЕ ЗОНЫ (Moderate >= 0.3x):{C_RESET}  {len(yellow_edges):5d} ({p_yellow:5.1f}%) {make_bar(p_yellow/100, 20, C_YELLOW)}")
                out.append(f"  {C_BOLD}{C_GREEN}ЗЕЛЕНЫЕ ЗОНЫ (Freeflow < 0.3x):{C_RESET}  {len(green_edges):5d} ({p_green:5.1f}%) {make_bar(p_green/100, 20, C_GREEN)}")
                
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
                        status = f"{C_BOLD}{C_MAGENTA}ПИТЧ-БЛЭК (Spillback){C_RESET}"
                        speed = f"{C_BOLD}{C_RED}0 км/ч (Стоит){C_RESET}"
                    elif r >= 1.0:
                        status = f"{C_RED}КРИТИЧЕСКИЙ ЗАДЕРЖКА{C_RESET}"
                        speed = f"{C_YELLOW}~5 - 12 км/ч{C_RESET}"
                    elif r >= 0.5:
                        status = f"{C_YELLOW}ЗАТОР (Тягуны){C_RESET}"
                        speed = f"{C_GREEN}~20 - 40 км/ч{C_RESET}"
                    else:
                        status = f"{C_GREEN}СВОБОДНО{C_RESET}"
                        speed = f"{C_GREEN}> 60 км/ч{C_RESET}"
                        
                    out.append(f"  {idx:2d} | {eid:15d} | {r:10.2f}x | {status:30s} | {speed}")
                
                out.append("--------------------------------------------------------------------------------")
                out.append(f"{C_YELLOW}Выход: Ctrl+C{C_RESET}")

                sys.stdout.write("\n".join(out))
                sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor back
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
        print(f"\n{C_BOLD}Мониторинг завершен.{C_RESET}")

if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        print("\nВыход...")
