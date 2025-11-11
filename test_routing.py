#!/usr/bin/env python3
"""
Test script for K-shortest paths routing through via points.

Tests the routing system with Arbat graph data.
"""

import sys
from pathlib import Path

# Add src to path  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))

from src.routing.graph import Graph  # noqa: E402
from src.routing.route_builder import build_routes  # noqa: E402
from src.data.postgis_manager import PostGISManager  # noqa: E402
from src.utils.logger import setup_logger, configure_structlog  # noqa: E402


configure_structlog(log_level="INFO")
log = setup_logger(__name__)


def test_simple_route():
    """Test simple 2-point routing (from → to)."""
    log.info("=" * 60)
    log.info("Test 1: Simple route (from → to)")
    log.info("=" * 60)

    # Load graph
    log.info("Loading graph from PostgreSQL...")
    db = PostGISManager()
    graph = Graph.load_from_db(db)
    stats = graph.get_stats()
    log.info("Graph loaded", **stats)

    # Arbat area coordinates (2 connected points)
    points = [
        (55.750857, 37.568329),  # Start (Node 1)
        (55.752473, 37.574029),  # End (Node 2)
    ]

    # Build routes
    log.info("Building routes", num_points=len(points), k=5)
    routes = build_routes(graph, points, k=5, snap_k=5)

    if not routes:
        log.error("No routes found!")
        return False

    log.info("Routes found", num_routes=len(routes))

    # Display results
    for route in routes:
        log.info(
            f"Route {route.id}",
            segments=len(route.segments),
            edges=len(route.edge_ids),
            distance_m=f"{route.total_distance_m:.1f}",
            time_sec=f"{route.total_time_sec:.1f}",
            geometry_points=len(route.geometry)
        )

    return True


def test_via_points():
    """Test routing with via points (from → via → to)."""
    log.info("=" * 60)
    log.info("Test 2: Route with via points (from → via → to)")
    log.info("=" * 60)

    # Load graph
    db = PostGISManager()
    graph = Graph.load_from_db(db)

    # Arbat area coordinates (3 points with via point)
    points = [
        (55.750857, 37.568329),  # Start (Node 1)
        (55.751647, 37.574886),  # Via point (Node 4)
        (55.752473, 37.574029),  # End (Node 2)
    ]

    # Build routes
    log.info("Building routes", num_points=len(points), k=5)
    routes = build_routes(graph, points, k=5, snap_k=5)

    if not routes:
        log.error("No routes found!")
        return False

    log.info("Routes found", num_routes=len(routes))

    # Display results
    for route in routes[:3]:  # Show top 3
        log.info(
            f"Route {route.id}",
            segments=len(route.segments),
            edges=len(route.edge_ids),
            distance_m=f"{route.total_distance_m:.1f}",
            time_sec=f"{route.total_time_sec:.1f}",
        )

        # Show segment details
        for seg in route.segments:
            log.debug(
                f"  Segment {seg.from_point_idx}→{seg.to_point_idx}",
                edges=len(seg.edge_ids),
                distance_m=f"{seg.distance_m:.1f}",
                time_sec=f"{seg.time_sec:.1f}"
            )

    return True


def test_multiple_via_points():
    """Test routing with multiple via points."""
    log.info("=" * 60)
    log.info("Test 3: Route with multiple via points")
    log.info("=" * 60)

    # Load graph
    db = PostGISManager()
    graph = Graph.load_from_db(db)

    # Arbat area coordinates (4 points)
    points = [
        (55.750857, 37.568329),  # Start (Node 1)
        (55.751098, 37.575349),  # Via 1 (Node 8)
        (55.752715, 37.573471),  # Via 2 (Node 9)
        (55.752473, 37.574029),  # End (Node 2)
    ]

    # Build routes
    log.info("Building routes", num_points=len(points), k=3)
    routes = build_routes(graph, points, k=3, snap_k=5)

    if not routes:
        log.error("No routes found!")
        return False

    log.info("Routes found", num_routes=len(routes))

    # Display best route
    best = routes[0]
    log.info(
        "Best route",
        segments=len(best.segments),
        edges=len(best.edge_ids),
        distance_m=f"{best.total_distance_m:.1f}",
        time_sec=f"{best.total_time_sec:.1f}",
        geometry_points=len(best.geometry)
    )

    return True


def main():
    """Run all tests."""
    log.info("Starting routing tests...")
    log.info("")

    tests = [
        test_simple_route,
        test_via_points,
        test_multiple_via_points,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
                log.info(f"✓ {test_func.__name__} PASSED")
            else:
                failed += 1
                log.error(f"✗ {test_func.__name__} FAILED")
        except Exception as e:
            failed += 1
            log.error(f"✗ {test_func.__name__} FAILED", error=str(e))

        log.info("")

    # Summary
    log.info("=" * 60)
    log.info("Test Summary")
    log.info("=" * 60)
    log.info(f"Passed: {passed}/{len(tests)}")
    log.info(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        log.info("All tests passed! ✓")
        return 0
    else:
        log.error(f"{failed} test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
