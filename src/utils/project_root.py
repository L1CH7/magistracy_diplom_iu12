"""
Project root detection utility.

Provides reliable PROJECT_ROOT without parent.parent.parent chains.
"""

import os
from pathlib import Path


def get_project_root() -> Path:
    """
    Get project root directory.
    
    Uses environment variable PROJECT_ROOT if set,
    otherwise searches for project markers (pyproject.toml, .git).
    
    Returns:
        Path to project root directory
    """
    # 1. Check environment variable
    env_root = os.getenv("PROJECT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    
    # 2. Search for project markers
    current = Path(__file__).resolve()
    
    # Traverse up until we find project markers
    for parent in [current] + list(current.parents):
        # Check for common project root markers
        if (
            (parent / "pyproject.toml").exists()
            or (parent / ".git").exists()
            or (parent / "docker-compose.yml").exists()
        ):
            return parent
    
    # 3. Fallback: assume src/utils/project_root.py structure
    # If we can't find markers, go up 2 levels from this file
    return current.parent.parent


# Cache result (computed once per process)
PROJECT_ROOT = get_project_root()
