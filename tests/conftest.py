import os
import sys


def pytest_sessionstart(session):  # type: ignore[no-redef]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if root not in sys.path:
        sys.path.insert(0, root)
