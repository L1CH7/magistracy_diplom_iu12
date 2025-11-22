"""
Integration tests for Coordinator API.
"""

import sys
from pathlib import Path
import pytest
from httpx import AsyncClient

# Add service root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import app  # noqa: E402


@pytest.fixture
async def client():
    """Create test client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client):
    """Test health check."""
    response = await client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data


@pytest.mark.asyncio
async def test_calculate_routes(client):
    """Test route calculation endpoint."""
    request = {
        "start_lat": 55.7558,
        "start_lon": 37.6173,
        "end_lat": 55.7522,
        "end_lon": 37.6156,
        "k": 3,
        "priority": 0,
        "agent_type": "car_normal"
    }
    
    response = await client.post("/api/v1/routes/calculate", json=request)
    
    assert response.status_code == 200
    data = response.json()
    assert "routes" in data


@pytest.mark.asyncio
async def test_create_agent(client):
    """Test agent creation endpoint."""
    # TODO: Mock Simulation Service
    pass


@pytest.mark.asyncio
async def test_remove_agent(client):
    """Test agent removal endpoint."""
    # TODO: Mock Simulation Service
    pass


@pytest.mark.asyncio
async def test_rerouting_status(client):
    """Test rerouting status endpoint."""
    response = await client.get("/api/v1/rerouting/status")
    
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data
    assert "strategy" in data
    assert data["strategy"] == "hybrid"


@pytest.mark.asyncio
async def test_websocket_connection(client):
    """Test WebSocket connection."""
    # TODO: Test WebSocket broadcasting
    pass
