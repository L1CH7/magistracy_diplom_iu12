import os
import json
import csv
import time
import random
import math
import pytest
from loguru import logger
from tests.utils import get_random_points, load_curated_waypoints
from tests.test_routing import calc_route_api

import os
import json
import csv
import time
import random
import math
import pytest
import httpx
from loguru import logger
from tests.utils import get_random_points, load_curated_waypoints
from tests.test_routing import calc_route_api

# Конфигурация путей
RESULTS_DIR = "/app/benchmarks/router/results"
BENCHMARK_PREFIX = os.getenv("BENCHMARK_PREFIX", "benchmark")
RESULTS_CSV = os.path.join(RESULTS_DIR, f"{BENCHMARK_PREFIX}_{os.getpid()}.csv")

# Persistent Client for connection pooling (Speedup!)
CLIENT = httpx.Client(timeout=60.0)

def haversine(lat1, lon1, lat2, lon2):
    """Рассчитывает расстояние по прямой (в км)."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def log_result_to_csv(data):
    """Записывает результат в CSV."""
    if not os.path.exists(RESULTS_DIR):
        try:
            os.makedirs(RESULTS_DIR, exist_ok=True)
        except Exception:
            pass # Race condition safe
            
    file_exists = os.path.isfile(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

def run_benchmark_case(waypoints, k):
    """Запуск единичного бенчмарка."""
    e_dist = 0
    for i in range(len(waypoints)-1):
        e_dist += haversine(waypoints[i]["lat"], waypoints[i]["lon"], 
                            waypoints[i+1]["lat"], waypoints[i+1]["lon"])

    start_time = time.perf_counter()
    # Use persistent client
    success, result = calc_route_api(waypoints, k=k, client=CLIENT)
    duration_ms = (time.perf_counter() - start_time) * 1000
    
    if duration_ms > 30000:
        logger.warning(f"Slow request detected: {duration_ms}ms for N={len(waypoints)}, K={k}")

    # Категоризация ошибок
    error_type = "None"
    if not success:
        res_str = str(result).lower()
        if "no route" in res_str:
            error_type = "No Path Found"
        elif "timeout" in res_str:
            error_type = "Timeout"
        else:
            error_type = "Other Error"

    metrics = {
        "timestamp": time.time(),
        "num_waypoints": len(waypoints),
        "euclidean_dist_km": round(e_dist, 3),
        "route_dist_km": 0.0,
        "tortuosity": 1.0,
        "k": k,
        "duration_ms": round(duration_ms, 2),
        "sei_ms_km": 0.0,
        "complexity_factor": round(e_dist * k * len(waypoints), 2),
        "inputs": json.dumps([{"lat": p["lat"], "lon": p["lon"]} for p in waypoints]),
        "success": int(success),
        "error_type": error_type
    }
    
    if success and result:
        main_route = result[0]
        r_dist = main_route.get("total_distance_m", 0) / 1000
        metrics["route_dist_km"] = round(r_dist, 3)
        if r_dist > 0:
            metrics["sei_ms_km"] = round(duration_ms / r_dist, 2)
        
        # Calculate Tortuosity (Route Length / Euclidean Distance)
        # 1.0 = Perfect straight line. >1.0 = winding road.
        if e_dist > 0.1 and r_dist > 0:
             metrics["tortuosity"] = round(r_dist / e_dist, 3)
        
    log_result_to_csv(metrics)
    return success

# Конфигурация
TOTAL_SAMPLES = int(os.getenv("NUM_SAMPLES", 1000))

@pytest.mark.parametrize("i", range(TOTAL_SAMPLES))
def test_load_generation(i):
    """
    Генерирует случайные задачи.
    pytest-xdist распределит эти задачи между воркерами.
    """
    points = load_curated_waypoints()
    if not points or len(points) < 5:
        pytest.skip("Not enough curated points")
        return

    # Random Config requested by user: N=[2..5], K=[1..5]
    n = random.choice([2, 3, 4, 5])
    k = random.choice([1, 2, 3, 4, 5])
    
    # Select N unique points
    try:
        sample_points = random.sample(points, n)
    except ValueError:
        pytest.skip("Sample error")
        return
    
    run_benchmark_case(sample_points, k)
