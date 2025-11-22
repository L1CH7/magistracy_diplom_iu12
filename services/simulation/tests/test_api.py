"""Tests for Simulation Service API."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add service root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import app  # noqa: E402


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_health_check(client):
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "simulation"
    assert "running" in data
    assert "agents" in data


def test_get_status(client):
    """Test status endpoint."""
    response = client.get("/simulation/status")
    assert response.status_code == 200
    
    data = response.json()
    assert "is_running" in data
    assert "fps" in data
    assert data["fps"] == 20
    assert "agent_count" in data
    assert "running_agents" in data
    assert "completed_agents" in data


def test_add_agent(client):
    """Test adding agent via API."""
    payload = {
        "route_edge_ids": [1, 2, 3, 4, 5],
        "start_lat": 55.751244,
        "start_lon": 37.618423,
        "agent_type": "car_normal"
    }
    
    response = client.post("/simulation/agents", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "agent_id" in data
    assert data["agent_id"].startswith("agent_")
    assert "position" in data
    assert data["position"]["lat"] == 55.751244
    assert data["position"]["lon"] == 37.618423


def test_add_agent_with_overrides(client):
    """Test adding agent with config overrides."""
    payload = {
        "route_edge_ids": [1, 2, 3],
        "start_lat": 55.0,
        "start_lon": 37.0,
        "agent_type": "car_hurry",
        "config_overrides": {
            "max_speed_override_kmh": 90
        }
    }
    
    response = client.post("/simulation/agents", json=payload)
    assert response.status_code == 200


def test_list_agents(client):
    """Test listing agents."""
    # Initially empty
    response = client.get("/simulation/agents")
    assert response.status_code == 200
    assert response.json()["count"] == 0
    
    # Add agent
    client.post("/simulation/agents", json={
        "route_edge_ids": [1, 2, 3],
        "start_lat": 55.0,
        "start_lon": 37.0,
        "agent_type": "car_normal"
    })
    
    # Should have one agent
    response = client.get("/simulation/agents")
    data = response.json()
    assert data["count"] == 1
    assert len(data["agents"]) == 1


def test_get_agent(client):
    """Test getting agent state."""
    # Add agent
    add_response = client.post("/simulation/agents", json={
        "route_edge_ids": [1, 2, 3],
        "start_lat": 55.0,
        "start_lon": 37.0,
        "agent_type": "car_normal"
    })
    agent_id = add_response.json()["agent_id"]
    
    # Get agent
    response = client.get(f"/simulation/agents/{agent_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["agent_id"] == agent_id
    assert "position" in data
    assert data["is_running"] is True
    assert data["reached_destination"] is False


def test_get_nonexistent_agent(client):
    """Test getting nonexistent agent."""
    response = client.get("/simulation/agents/nonexistent")
    assert response.status_code == 404


def test_remove_agent(client):
    """Test removing agent."""
    # Add agent
    add_response = client.post("/simulation/agents", json={
        "route_edge_ids": [1, 2, 3],
        "start_lat": 55.0,
        "start_lon": 37.0,
        "agent_type": "car_normal"
    })
    agent_id = add_response.json()["agent_id"]
    
    # Remove agent
    response = client.delete(f"/simulation/agents/{agent_id}")
    assert response.status_code == 200
    
    # Should not exist anymore
    response = client.get(f"/simulation/agents/{agent_id}")
    assert response.status_code == 404


def test_update_route(client):
    """Test updating agent route."""
    # Add agent
    add_response = client.post("/simulation/agents", json={
        "route_edge_ids": [1, 2, 3],
        "start_lat": 55.0,
        "start_lon": 37.0,
        "agent_type": "car_normal"
    })
    agent_id = add_response.json()["agent_id"]
    
    # Update route
    new_route = {"route_edge_ids": [4, 5, 6]}
    response = client.put(
        f"/simulation/agents/{agent_id}/route",
        json=new_route
    )
    assert response.status_code == 200
    
    data = response.json()
    assert "status" in data
    # Should succeed (no validation yet)
    assert data["status"] in ["switched", "cannot_switch"]


def test_start_stop_simulation(client):
    """Test starting and stopping simulation."""
    # Start
    response = client.post("/simulation/start")
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    
    # Check running
    status = client.get("/simulation/status").json()
    assert status["is_running"] is True
    
    # Stop
    response = client.post("/simulation/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    
    # Check not running
    status = client.get("/simulation/status").json()
    assert status["is_running"] is False


def test_start_already_running(client):
    """Test starting already running simulation."""
    client.post("/simulation/start")
    
    # Try starting again
    response = client.post("/simulation/start")
    assert response.status_code == 400
    
    # Clean up
    client.post("/simulation/stop")


def test_stop_not_running(client):
    """Test stopping not running simulation."""
    response = client.post("/simulation/stop")
    assert response.status_code == 400
