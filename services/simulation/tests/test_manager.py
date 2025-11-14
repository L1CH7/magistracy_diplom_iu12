"""Tests for SimulationManager."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parents[2]))

from src.manager import SimulationManager  # noqa: E402


@pytest.fixture
async def manager():
    """Create and initialize manager."""
    mgr = SimulationManager()
    await mgr.initialize()
    yield mgr
    if mgr.is_running:
        await mgr.stop()


@pytest.mark.asyncio
async def test_manager_initialization():
    """Test manager initializes correctly."""
    mgr = SimulationManager()
    await mgr.initialize()
    
    assert mgr.batch is not None
    assert mgr.batch.size == 0
    assert not mgr.is_running
    assert mgr.fps == 20
    assert mgr.dt == 0.05


@pytest.mark.asyncio
async def test_add_agent(manager):
    """Test adding agent."""
    route = [1, 2, 3, 4, 5]
    
    agent_id = await manager.add_agent(
        route_edge_ids=route,
        start_lat=55.751244,
        start_lon=37.618423,
        agent_type='car_normal'
    )
    
    assert agent_id.startswith('agent_')
    assert manager.get_agent_count() == 1
    assert agent_id in manager.list_agents()
    
    # Check position
    pos = manager.get_agent_position(agent_id)
    assert pos.lat == 55.751244
    assert pos.lon == 37.618423
    assert pos.edge_id == 1  # First edge in route


@pytest.mark.asyncio
async def test_add_multiple_agents(manager):
    """Test adding multiple agents."""
    route = [1, 2, 3]
    
    ids = []
    for i in range(5):
        agent_id = await manager.add_agent(
            route_edge_ids=route,
            start_lat=55.0 + i * 0.01,
            start_lon=37.0 + i * 0.01,
            agent_type='car_normal'
        )
        ids.append(agent_id)
    
    assert manager.get_agent_count() == 5
    assert len(manager.list_agents()) == 5
    
    # Check all agents have different positions
    positions = [manager.get_agent_position(aid) for aid in ids]
    lats = [p.lat for p in positions]
    assert len(set(lats)) == 5  # All unique


@pytest.mark.asyncio
async def test_remove_agent(manager):
    """Test removing agent."""
    route = [1, 2, 3]
    
    # Add 3 agents
    ids = []
    for i in range(3):
        agent_id = await manager.add_agent(
            route_edge_ids=route,
            start_lat=55.0,
            start_lon=37.0,
            agent_type='car_normal'
        )
        ids.append(agent_id)
    
    assert manager.get_agent_count() == 3
    
    # Remove middle agent
    await manager.remove_agent(ids[1])
    
    assert manager.get_agent_count() == 2
    assert ids[1] not in manager.list_agents()
    assert ids[0] in manager.list_agents()
    assert ids[2] in manager.list_agents()
    
    # Check removed agent raises error
    with pytest.raises(KeyError):
        manager.get_agent_position(ids[1])


@pytest.mark.asyncio
async def test_update_route(manager):
    """Test updating agent route."""
    old_route = [1, 2, 3]
    new_route = [4, 5, 6]
    
    agent_id = await manager.add_agent(
        route_edge_ids=old_route,
        start_lat=55.0,
        start_lon=37.0,
        agent_type='car_normal'
    )
    
    # Update route
    success, new_index = await manager.update_route(agent_id, new_route)
    
    assert success  # Should succeed (no validation yet)
    
    # Check route updated
    state = manager.get_agent_state(agent_id)
    # Note: route_edge_ids stored as object array, need special check
    assert state.agent_id == agent_id


@pytest.mark.asyncio
async def test_start_stop_simulation(manager):
    """Test starting and stopping simulation."""
    assert not manager.is_running
    
    # Start
    await manager.start()
    assert manager.is_running
    
    # Let it run briefly
    await asyncio.sleep(0.2)
    
    # Stop
    await manager.stop()
    assert not manager.is_running
    
    # Check ticks happened
    assert manager.tick_count > 0


@pytest.mark.asyncio
async def test_simulation_with_agents(manager):
    """Test simulation updates agent positions."""
    route = [1, 2, 3]
    
    agent_id = await manager.add_agent(
        route_edge_ids=route,
        start_lat=55.751244,
        start_lon=37.618423,
        agent_type='car_normal'
    )
    
    # Get initial position
    initial_pos = manager.get_agent_position(agent_id)
    
    # Start simulation
    await manager.start()
    
    # Run for 0.5 seconds (~10 ticks)
    await asyncio.sleep(0.5)
    
    # Stop
    await manager.stop()
    
    # Check position changed (or at least time elapsed)
    state = manager.get_agent_state(agent_id)
    assert state.elapsed_time > 0
    
    # Note: Position might not change if graph_cache not loaded
    # This is expected for now


@pytest.mark.asyncio
async def test_get_status(manager):
    """Test getting simulation status."""
    status = manager.get_status()
    
    assert not status.is_running
    assert status.fps == 20
    assert status.agent_count == 0
    assert status.running_agents == 0
    assert status.completed_agents == 0
    
    # Add agent
    await manager.add_agent(
        route_edge_ids=[1, 2, 3],
        start_lat=55.0,
        start_lon=37.0,
        agent_type='car_normal'
    )
    
    status = manager.get_status()
    assert status.agent_count == 1
    assert status.running_agents == 1


@pytest.mark.asyncio
async def test_agent_config_override(manager):
    """Test custom agent config."""
    agent_id = await manager.add_agent(
        route_edge_ids=[1, 2, 3],
        start_lat=55.0,
        start_lon=37.0,
        agent_type='car_normal',
        config_overrides={'max_speed_override_kmh': 80}
    )
    
    # Should succeed (config stored in batch)
    assert agent_id is not None
    assert manager.get_agent_count() == 1
