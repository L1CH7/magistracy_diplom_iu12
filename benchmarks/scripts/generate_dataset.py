import os
import json
import random
import httpx
import time
from loguru import logger

# Configuration
# Prefer internal service URL from env, fallback to internal docker DNS
ROUTER_URL = os.getenv("APP__SERVICES__ROUTER__URL", "http://router:8000") 
if not ROUTER_URL.endswith("/api/v1/routing/calculate"):
    ROUTER_URL = f"{ROUTER_URL}/api/v1/routing/calculate"

logger.info(f"Target Router URL: {ROUTER_URL}")
OUTPUT_FILE = "benchmarks/data/router/golden_dataset.json"
WAYPOINTS_FILE = "/app/tests/waypoints.json"
NUM_SAMPLES_PER_CATEGORY = 10  # How many valid routes to find per category
MAX_ATTEMPTS = 500

# Geo Bounding Box (Moscow Region approx)
LAT_MIN, LAT_MAX = 55.5, 56.0
LON_MIN, LON_MAX = 37.3, 37.9

CATEGORIES = {
    "urban": (0, 5),      # 0-5 km
    "suburban": (5, 20),  # 5-20 km
    "intercity": (20, 100)# 20+ km
}

def load_curated_points():
    if os.path.exists(WAYPOINTS_FILE):
        try:
            with open(WAYPOINTS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load waypoints: {e}")
    logger.warning("Curated waypoints not found, using random generation.")
    return None

CURATED_POINTS = load_curated_points()

def get_random_point():
    if CURATED_POINTS:
        return random.choice(CURATED_POINTS)
    return {
        "lat": random.uniform(LAT_MIN, LAT_MAX),
        "lon": random.uniform(LON_MIN, LON_MAX)
    }

def check_route(p1, p2):
    try:
        # Avoid same point
        if abs(p1['lat'] - p2['lat']) < 0.0001 and abs(p1['lon'] - p2['lon']) < 0.0001:
            return None
            
        payload = {"waypoints": [p1, p2], "k": 1}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(ROUTER_URL, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data["routes"]:
                    return data["routes"][0]["total_distance_m"] / 1000.0
    except Exception as e:
        logger.warning(f"Check failed: {e}")
        pass
    return None

def generate_dataset():
    dataset = {cat: [] for cat in CATEGORIES}
    
    logger.info("Starting Golden Dataset generation...")
    
    for cat, (min_dist, max_dist) in CATEGORIES.items():
        found = 0
        attempts = 0
        while found < NUM_SAMPLES_PER_CATEGORY and attempts < MAX_ATTEMPTS:
            attempts += 1
            p1 = get_random_point()
            p2 = get_random_point()
            
            dist_km = check_route(p1, p2)
            
            if dist_km and min_dist <= dist_km < max_dist:
                dataset[cat].append({
                    "waypoints": [p1, p2],
                    "expected_dist_km": round(dist_km, 3)
                })
                found += 1
                print(f"[{cat.upper()}] Found {found}/{NUM_SAMPLES_PER_CATEGORY} ({dist_km:.2f} km)")
                
        if found < NUM_SAMPLES_PER_CATEGORY:
            logger.warning(f"Could not fill category {cat}: found {found}/{NUM_SAMPLES_PER_CATEGORY}")

    # Save to file
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(dataset, f, indent=2)
    
    logger.success(f"Golden Dataset saved to {OUTPUT_FILE}")
    total = sum(len(v) for v in dataset.values())
    logger.info(f"Total routes: {total}")

if __name__ == "__main__":
    generate_dataset()
