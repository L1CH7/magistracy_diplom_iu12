#!/usr/bin/env python3
"""
Test script for GraphBuilder.
Run from diplom/ directory: python scripts/test_graph_builder.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'router'))

# Now run GraphBuilder
from src.graph.graph_builder import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
