#!/usr/bin/env python3
"""Build graph from Arbat area OSM data and save to PostgreSQL.

This script:
1. Fetches OSM data for Arbat bbox (or uses cached data)
2. Builds graph (nodes + edges)
3. Saves to PostgreSQL (nodes and edges tables)
4. Displays statistics

Usage:
    python scripts/build_graph_arbat.py [--force-fetch]
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.graph_builder import save_graph_to_postgres
from src.data.postgis_manager import PostGISManager
from src.data.osm_overpass import fetch_overpass, build_highway_query
from src.utils.logger import setup_logger

log = setup_logger(__name__)

# Arbat test bbox (from data_config.py)
ARBAT_BBOX = [37.5609, 55.7510, 37.6016, 55.7631]


def load_cached_osm_data(filepath: str = "data/osm_data.json") -> dict:
    """Load OSM data from cache file if exists."""
    cache_path = Path(filepath)
    if cache_path.exists():
        log.info(f"Loading cached OSM data from {cache_path}")
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            elements_count = len(data.get('elements', []))
            log.info(f"Loaded {elements_count} elements from cache")
            return data
    else:
        log.warning(f"Cache file {cache_path} not found")
        return None


def save_osm_data_cache(data: dict, filepath: str = "data/osm_data.json"):
    """Save OSM data to cache file."""
    cache_path = Path(filepath)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    elements_count = len(data.get('elements', []))
    log.info(f"Saved {elements_count} elements to cache: {cache_path}")


def fetch_arbat_osm_data(force_fetch: bool = False) -> dict:
    """Fetch OSM data for Arbat area (or use cache).
    
    Args:
        force_fetch: If True, fetch from Overpass API even if cache exists
        
    Returns:
        Overpass API JSON response
    """
    # Try cache first
    if not force_fetch:
        cached = load_cached_osm_data()
        if cached:
            return cached
    
    # Fetch from Overpass API
    log.info(f"Fetching OSM data for Arbat bbox: {ARBAT_BBOX}")
    min_lon, min_lat, max_lon, max_lat = ARBAT_BBOX
    
    # Build Overpass query (south, west, north, east)
    query = build_highway_query((min_lat, min_lon, max_lat, max_lon))
    data = fetch_overpass(query, timeout=180)
    
    # Save to cache
    save_osm_data_cache(data)
    
    return data


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build graph from Arbat OSM data"
    )
    parser.add_argument(
        '--force-fetch',
        action='store_true',
        help='Force fetch from Overpass API (ignore cache)'
    )
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("Building Arbat graph and saving to PostgreSQL")
    log.info("=" * 60)
    
    try:
        # Step 1: Get OSM data
        log.info("Step 1: Fetching OSM data...")
        osm_data = fetch_arbat_osm_data(force_fetch=args.force_fetch)
        
        elements = osm_data.get('elements', [])
        nodes_count = len([e for e in elements if e.get('type') == 'node'])
        ways_count = len([e for e in elements if e.get('type') == 'way'])
        log.info(f"OSM data: {nodes_count} nodes, {ways_count} ways")
        
        # Step 2: Connect to PostgreSQL
        log.info("Step 2: Connecting to PostgreSQL...")
        db = PostGISManager()
        
        # Step 3: Build and save graph
        log.info("Step 3: Building graph and saving to database...")
        save_graph_to_postgres(osm_data, db)
        
        # Step 4: Display statistics
        log.info("Step 4: Getting graph statistics...")
        stats = db.get_graph_stats()
        
        log.info("=" * 60)
        log.info("GRAPH BUILD COMPLETE")
        log.info("=" * 60)
        log.info(f"Total nodes:       {stats.get('total_nodes', 0)}")
        log.info(f"Total edges:       {stats.get('total_edges', 0)}")
        total_km = stats.get('total_length_km', 0)
        log.info(f"Total length:      {total_km:.2f} km")
        avg_len = stats.get('avg_edge_length_m', 0)
        log.info(f"Avg edge length:   {avg_len:.1f} m")
        log.info(f"Avg lanes:         {stats.get('avg_lanes', 0):.1f}")
        total_cap = stats.get('total_capacity', 0)
        log.info(f"Total capacity:    {total_cap} agents")
        
        highway_types = stats.get('highway_types', {})
        if highway_types:
            log.info("\nHighway types distribution:")
            for htype, count in sorted(
                highway_types.items(),
                key=lambda x: x[1],
                reverse=True
            ):
                log.info(f"  {htype:20s}: {count}")
        
        log.info("=" * 60)
        
    except Exception as e:
        log.error(f"Graph build FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
