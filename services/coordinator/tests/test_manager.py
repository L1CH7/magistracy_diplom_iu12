"""
Unit tests for CoordinatorManager.
"""

import sys
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

# Add service root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.manager import CoordinatorManager  # noqa: E402


@pytest.fixture
async def manager():
    """Create manager instance."""
    mgr = CoordinatorManager()
    await mgr.initialize()
    yield mgr
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_initialize():
    """Test manager initialization."""
    mgr = CoordinatorManager()
    await mgr.initialize()
    
    assert mgr.http_client is not None
    
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_calculate_routes_basic(manager):
    """Test basic route calculation."""
    routes = await manager.calculate_routes(
        start_lat=55.7558,
        start_lon=37.6173,
        end_lat=55.7522,
        end_lon=37.6156,
        k=3
    )
    
    assert isinstance(routes, list)
    # Currently mock, will test real logic in Phase 4


@pytest.mark.asyncio
async def test_create_agent(manager):
    """Test agent creation."""
    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"agent_id": "test_agent_1"}
    
    manager.http_client.post = AsyncMock(return_value=mock_response)
    
    agent_id = await manager.create_agent(
        start_lat=55.7558,
        start_lon=37.6173,
        end_lat=55.7522,
        end_lon=37.6156,
        route_edge_ids=[1, 2, 3]
    )
    
    assert agent_id == "test_agent_1"
    assert agent_id in manager.agents


@pytest.mark.asyncio
async def test_remove_agent(manager):
    """Test agent removal."""
    # Add agent first
    manager.agents["test_agent_1"] = {
        "priority": 0,
        "agent_type": "car_normal"
    }
    
    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    manager.http_client.delete = AsyncMock(return_value=mock_response)
    
    await manager.remove_agent("test_agent_1")
    
    assert "test_agent_1" not in manager.agents


@pytest.mark.asyncio
async def test_remove_agent_not_found(manager):
    """Test removing non-existent agent."""
    with pytest.raises(KeyError):
        await manager.remove_agent("nonexistent")


@pytest.mark.asyncio
async def test_get_agent_count(manager):
    """Test agent count."""
    assert manager.get_agent_count() == 0
    
    manager.agents["agent1"] = {}
    manager.agents["agent2"] = {}
    
    assert manager.get_agent_count() == 2


@pytest.mark.asyncio
async def test_get_rerouting_status(manager):
    """Test rerouting status."""
    status = await manager.get_rerouting_status()
    
    assert status["enabled"] is True
    assert status["strategy"] == "hybrid"
    assert status["check_interval_sec"] == 5
    assert "agents_rerouted" in status
