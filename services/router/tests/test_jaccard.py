import os
import json
import csv
import time
import random
import math
import asyncio
import httpx
import pytest
from loguru import logger

from tests.utils import get_random_points, get_distant_random_points
from tests.test_routing import calc_route_api

# RESULTS CONFIG
RESULTS_DIR = "/app/benchmarks/router/results"
RESULTS_CSV = os.path.join(RESULTS_DIR, "jaccard_results.csv")

# PERSISTENT CLIENT
CLIENT = httpx.Client(timeout=120.0)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_jaccard(edges1, edges2):
    """Calculates Jaccard Similarity between two sets of edge IDs."""
    set1 = set(edges1)
    set2 = set(edges2)
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0

def calculate_pdi(all_routes_edges):
    """
    Calculates Path Diversity Index (PDI).
    PDI = (Unique Edges across all paths) / (Sum of lengths of all paths)
    """
    if not all_routes_edges:
        return 0.0
    
    unique_edges = set()
    total_edges_count = 0
    for edges in all_routes_edges:
        unique_edges.update(edges)
        total_edges_count += len(edges)
    
    if total_edges_count == 0:
        return 0.0
        
    return len(unique_edges) / total_edges_count

def log_jaccard_to_csv(data):
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR, exist_ok=True)
            
    file_exists = os.path.isfile(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

async def run_jaccard_benchmark(n_points=2):
    if n_points == 2:
        # Use distant points to test highway diversity
        points = await get_distant_random_points(min_dist_km=4.0)
    else:
        points = await get_random_points(n_points)
        
    if not points:
        return
    
    # We want K=5
    k = 5
    
    # Calculate Euclidean distance
    e_dist = 0
    for i in range(len(points)-1):
        e_dist += haversine(points[i]["lat"], points[i]["lon"], 
                            points[i+1]["lat"], points[i+1]["lon"])
    
    start_time = time.perf_counter()
    success, routes = calc_route_api(points, k=k, client=CLIENT)
    duration_ms = (time.perf_counter() - start_time) * 1000
    
    if not success or not routes:
        logger.warning(f"Jaccard Test: No route found for N={n_points}")
        return

    # Extract edge sets
    all_edges = [r.get("edge_ids", []) for r in routes]
    actual_k = len(routes)
    
    # Pairwise Jaccard
    jaccard_values = []
    for i in range(actual_k):
        for j in range(i + 1, actual_k):
            j_val = calculate_jaccard(all_edges[i], all_edges[j])
            jaccard_values.append(j_val)
    
    avg_jaccard = sum(jaccard_values) / len(jaccard_values) if jaccard_values else 1.0
    min_jaccard = min(jaccard_values) if jaccard_values else 1.0
    max_jaccard = max(jaccard_values) if jaccard_values else 1.0
    
    # Path Diversity Index
    pdi = calculate_pdi(all_edges)
    
    # Metrics for the first route (benchmark)
    main_route = routes[0]
    r_dist = main_route.get("total_distance_m", 0) / 1000
    
    metrics = {
        "timestamp": time.time(),
        "n_waypoints": n_points,
        "k_requested": k,
        "k_actual": actual_k,
        "euclidean_dist_km": round(e_dist, 3),
        "route_dist_km": round(r_dist, 3),
        "duration_ms": round(duration_ms, 2),
        "avg_jaccard": round(avg_jaccard, 4),
        "min_jaccard": round(min_jaccard, 4),
        "max_jaccard": round(max_jaccard, 4),
        "pdi": round(pdi, 4),
        "tortuosity": round(r_dist / e_dist, 3) if e_dist > 0.1 else 1.0
    }
    
    log_jaccard_to_csv(metrics)
    logger.info(f"Jaccard result: PDI={metrics['pdi']}, AvgJ={metrics['avg_jaccard']} for dist={metrics['route_dist_km']}km")

@pytest.mark.parametrize("sample_idx", range(100)) # 100 samples for robust statistics
def test_jaccard_diversity(sample_idx):
    # N is 2 or 3 as requested
    n = random.choice([2, 3])
    
    # pytest + async loop
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_jaccard_benchmark(n_points=n))
