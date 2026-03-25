import os
import pytest
import httpx
from loguru import logger

# Конфигурация: приоритет переменной окружения, затем localhost (для локального запуска), затем 'router' (для Docker)
ROUTER_URL = os.getenv("APP__SERVICES__ROUTER__URL", "http://localhost:8006")
if "api/v1" not in ROUTER_URL:
    ROUTER_URL = f"{ROUTER_URL.rstrip('/')}/api/v1/routing/calculate"
else:
    ROUTER_URL = ROUTER_URL.rstrip('/')

from tests.utils import get_random_points, load_curated_waypoints

def calc_route_api(waypoints: list, k: int = 1, client: httpx.Client = None):
    """
    Вспомогательная функция для вызова API маршрутизации (синхронная версия).
    """
    payload = {
        "waypoints": waypoints,
        "k": k,
        "priority": 0
    }
    
    def _make_request(c):
        return c.post(ROUTER_URL, json=payload)

    try:
        if client:
            response = _make_request(client)
        else:
            with httpx.Client(timeout=60.0) as c:
                response = _make_request(c)
                
        if response.status_code != 200:
            # Only log errors if not 404 (No Path is expected)
            if response.status_code != 404:
                logger.error(f"Routing failed ({response.status_code}): {response.text}")
            return False, response.text
            
        data = response.json()
        routes = data.get("routes", [])
        
        if not routes:
            return False, "No routes"
            
        return True, routes
    except Exception as e:
        logger.warning(f"Request failed: {e}")
        return False, str(e)

def test_routing_logic(db_schema):
    """
    Проверяет построение маршрута (функциональный тест) на отобранных точках.
    Последовательное исполнение.
    """
    points = load_curated_waypoints()
    if not points:
        pytest.skip("Curated waypoints.json not found or empty")
        
    # Пробуем последовательно разные пары из списка, пока не найдем связную
    # (или пока список не кончится)
    found_any = False
    for i in range(len(points) - 1):
        success, result = calc_route_api([points[i], points[i+1]], k=1)
        if success:
            assert len(result) >= 1
            found_any = True
            break
            
    if not found_any:
        pytest.fail("Could not find a routable pair in the curated waypoints.json")

def test_basic_functional():
    """Простейший тест для проверки работоспособности API (последовательно)."""
    points = load_curated_waypoints()
    if not points:
        pytest.skip("No curated points")
    
    # Для базового теста просто проверяем, что API отвечает
    with httpx.Client(timeout=60.0) as client:
        payload = {"waypoints": points[:2], "k": 1}
        response = client.post(ROUTER_URL, json=payload)
        assert response.status_code in (200, 404)
