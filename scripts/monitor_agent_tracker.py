#!/usr/bin/env python3
import time
import json
import os
import csv
import hashlib
import argparse
import http.client
from urllib.parse import urlparse
from collections import defaultdict
from typing import Dict, Any, List

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"

BASE_URL = "http://localhost:8000"

def fetch_json(path: str) -> Dict[str, Any]:
    try:
        url = urlparse(BASE_URL + path)
        conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=2.0)
        conn.request("GET", url.path + ("?" + url.query if url.query else ""))
        resp = conn.getresponse()
        if resp.status == 200:
            raw = resp.read().decode('utf-8')
            parsed = json.loads(raw)
            conn.close()
            return parsed
        conn.close()
    except Exception:
        pass
    return {}

class AgentTracker:
    def __init__(self, agent_id: int):
        self.agent_id = agent_id
        self.edges_traversed = set()
        self.stuck_episodes = 0
        self.last_status = None
        self.last_edge = None

    def update(self, status: str, edge: int):
        if self.last_edge is None or edge != self.last_edge:
            if edge != 0:
                self.edges_traversed.add(edge)
            self.last_edge = edge

        if status == "ACTIVE_QUEUE" and self.last_status != "ACTIVE_QUEUE":
            self.stuck_episodes += 1

        self.last_status = status

def main():
    parser = argparse.ArgumentParser(description="Traffic Core Agent & Bottleneck Tracker")
    parser.add_argument("--count", type=int, default=2000, help="Number of active agents to sample and track")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    args = parser.parse_args()

    print(f"{C_BOLD}{C_CYAN}=== Traffic Core Agent Diagnostics & CSV Collector (Advanced) ==={C_RESET}")
    print(f"Sampling {args.count} active agents every {args.interval}s on-demand...\n")

    agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats", "agents")
    os.makedirs(agents_dir, exist_ok=True)

    date_str = time.strftime("%d-%m-%Y")
    run_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    csv_filename = os.path.join(agents_dir, f"run_{date_str}_{run_hash}_agents_sample_{args.count}a.csv")

    csv_headers = [
        "SimTime", "SampleCount", "FreeFlowCount", "StuckQueueCount", 
        "VirtualBufferCount", "InactiveCount", "AvgStuckSec", "MaxStuckSec", 
        "AvgSpeedMps", "AvgRouteTotal", "AvgRouteProgressPct", "AvgTripSec",
        "AvgBufferInSec", "AvgBufferEdges",
        "Edge0Count", "LimboPhantomCount", "UniqueStuckEdges", "TopBottleneckEdge", 
        "TopBottleneckCount", "TotalStuckEpisodes"
    ]

    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(csv_headers)

    print(f"{C_BOLD}{C_GREEN}[+] Расширенная телеметрия сохраняется в: {os.path.basename(csv_filename)}{C_RESET}\n")

    trackers: Dict[int, AgentTracker] = {}
    stuck_edges_counter = defaultdict(int)
    last_logged_sim_time = -100.0

    try:
        while True:
            t0 = time.time()

            sample_resp = fetch_json(f"/api/v1/debug/agent_sample?count={args.count}")
            stats_resp = fetch_json("/api/v1/sim/stats")

            sim_stats = stats_resp.get("data", {}) if stats_resp.get("status") == "success" else {}
            sample_data = sample_resp.get("data", {}) if sample_resp.get("status") == "success" else {}

            sim_time = sample_data.get("sim_time", sim_stats.get("sim_time", 0.0))
            agents_list = sample_data.get("agents", [])

            if not agents_list:
                time.sleep(args.interval)
                continue

            stuck_now = 0
            free_flow_now = 0
            virt_buf_now = 0
            inactive_now = 0
            edge0_cnt = 0
            limbo_cnt = 0

            stuck_times = []
            speeds = []
            route_totals = []
            progress_pcts = []
            trip_secs = []
            buffer_in_secs = []
            buffer_edges_list = []

            for ag in agents_list:
                aid = ag["id"]
                st = ag["status"]
                edge = ag["edge"]
                v = ag["v"]
                wait_sec = ag.get("spillback_wait_sec", 0)
                r_idx = ag.get("route_idx", 0)
                r_tot = ag.get("route_total", 0)
                t_sec = ag.get("trip_sec", 0)

                if aid not in trackers:
                    trackers[aid] = AgentTracker(aid)
                trackers[aid].update(st, edge)

                speeds.append(v)
                if r_tot > 0:
                    route_totals.append(r_tot)
                    progress_pcts.append((r_idx / max(1, r_tot)) * 100.0)
                if t_sec > 0:
                    trip_secs.append(t_sec)

                if edge == 0:
                    edge0_cnt += 1

                if st == "ACTIVE_QUEUE":
                    stuck_now += 1
                    stuck_times.append(wait_sec)
                    if edge != 0:
                        stuck_edges_counter[edge] += 1
                    if r_tot == 0:
                        limbo_cnt += 1
                elif st == "VIRTUAL_BUFFER":
                    virt_buf_now += 1
                    buf_sec = ag.get("buffer_in_sec", 0)
                    buf_edg = ag.get("buffer_edges", 0)
                    buffer_in_secs.append(buf_sec)
                    buffer_edges_list.append(buf_edg)
                elif st == "ACTIVE_FREE_FLOW":
                    free_flow_now += 1
                else:
                    inactive_now += 1

            avg_stuck = (sum(stuck_times) / len(stuck_times)) if stuck_times else 0.0
            max_stuck = max(stuck_times) if stuck_times else 0.0
            avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0
            avg_rtot = (sum(route_totals) / len(route_totals)) if route_totals else 0.0
            avg_prog = (sum(progress_pcts) / len(progress_pcts)) if progress_pcts else 0.0
            avg_tsec = (sum(trip_secs) / len(trip_secs)) if trip_secs else 0.0
            avg_buf_sec = (sum(buffer_in_secs) / len(buffer_in_secs)) if buffer_in_secs else 0.0
            avg_buf_edg = (sum(buffer_edges_list) / len(buffer_edges_list)) if buffer_edges_list else 0.0

            top_edge = 0
            top_cnt = 0
            if stuck_edges_counter:
                top_edge, top_cnt = max(stuck_edges_counter.items(), key=lambda x: x[1])

            total_episodes = sum(t.stuck_episodes for t in trackers.values())

            # Log to CSV if sim_time progressed
            if sim_time > last_logged_sim_time:
                with open(csv_filename, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        round(sim_time, 2), len(agents_list), free_flow_now, stuck_now,
                        virt_buf_now, inactive_now, round(avg_stuck, 2), round(max_stuck, 2),
                        round(avg_speed, 2), round(avg_rtot, 1), round(avg_prog, 2), round(avg_tsec, 1),
                        round(avg_buf_sec, 2), round(avg_buf_edg, 2),
                        edge0_cnt, limbo_cnt, len(stuck_edges_counter), top_edge,
                        top_cnt, total_episodes
                    ])
                last_logged_sim_time = sim_time

            # Console Output: Concise Summary
            driving_total = free_flow_now + stuck_now + virt_buf_now
            stuck_pct = (stuck_now / driving_total * 100.0) if driving_total > 0 else 0.0
            avg_speed_kmh = avg_speed * 3.6

            print(f"\r{C_BOLD}[SimTime: {sim_time:8.1f}s]{C_RESET} "
                  f"На дорогах: {driving_total:4d} | "
                  f"Едут: {C_GREEN}{free_flow_now:4d}{C_RESET} | "
                  f"Застряли: {C_RED}{stuck_now:4d} ({stuck_pct:4.1f}%){C_RESET} | "
                  f"Скорость: {C_CYAN}{avg_speed_kmh:4.1f} км/ч{C_RESET} | "
                  f"Прогресс: {C_YELLOW}{avg_prog:4.1f}%{C_RESET} | "
                  f"Фантомы: {C_MAGENTA}{limbo_cnt:2d}{C_RESET}", end="", flush=True)

            dt_took = time.time() - t0
            sleep_time = max(0.1, args.interval - dt_took)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n\n{C_BOLD}{C_GREEN}[+] Сбор данных завершен. Данные сохранены в:{C_RESET}")
        print(f"    {csv_filename}")
        print(f"{C_CYAN}Для визуализации запустите:{C_RESET}")
        print(f"    python3 scripts/stats/agents/analyze_agents.py {csv_filename}\n")

if __name__ == "__main__":
    main()
