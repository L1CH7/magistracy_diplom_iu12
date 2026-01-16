"""Agent movement and physics module."""
from .movement import (
    move,
    detect_teleport,
    can_switch_route
)
from .movement_batch import (
    AgentBatch,
    GraphCache,
    move_batch,
    detect_teleports_batch,
    benchmark_batch_movement
)
from .config import (
    AgentConfigManager,
    get_agent_config_manager
)

__all__ = [
    # Single agent functions
    'move',
    'detect_teleport',
    'can_switch_route',
    # Batch operations
    'AgentBatch',
    'GraphCache',
    'move_batch',
    'detect_teleports_batch',
    'benchmark_batch_movement',
    # Config management
    'AgentConfigManager',
    'get_agent_config_manager'
]
