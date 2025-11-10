"""Graph building utilities from OSM Overpass data with PostgreSQL persistence.

This module builds graphs from OSM data and saves them to PostgreSQL.
For R&D-1 simplification: one OSM way = one edge (no splitting by segments).
"""

from typing import Dict, Any, List, Tuple
import math
import networkx as nx
from src.data.postgis_manager import PostGISManager
from src.utils.logger import setup_logger

log = setup_logger(__name__)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points (meters)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def parse_speed(maxspeed: Any) -> float:
    """Parse OSM maxspeed tag, return m/s with sane default (50 km/h)."""
    if maxspeed is None:
        return 13.89
    try:
        if isinstance(maxspeed, (int, float)):
            return max(1.0, float(maxspeed) / 3.6)
        digits = "".join(ch for ch in str(maxspeed) if ch.isdigit())
        return max(1.0, float(digits) / 3.6) if digits else 13.89
    except Exception:
        return 13.89


def build_graph_from_overpass(data: Dict[str, Any]) -> nx.DiGraph:
    """Convert Overpass JSON to directed graph with attributes.

    Node attrs: lat, lon
    Edge attrs: length_m, max_speed, lanes, oneway, time_s
    """
    nodes = {
        el["id"]: el
        for el in data.get("elements", [])
        if el.get("type") == "node"
    }
    ways = [el for el in data.get("elements", []) if el.get("type") == "way"]

    G = nx.DiGraph()
    for nid, n in nodes.items():
        # Overpass nodes include 'lat' and 'lon'; keep as-is
        G.add_node(nid, lat=n['lat'], lon=n['lon'])

    for w in ways:
        tags = w.get("tags", {})
        if not tags.get("highway"):
            continue
        oneway = tags.get("oneway") in ("yes", "true", "1")
        lanes_tag = str(tags.get("lanes", "1"))
        lanes = int(lanes_tag) if lanes_tag.isdigit() else 1
        max_speed = parse_speed(tags.get("maxspeed"))
        node_ids = w.get("nodes", [])
        for u, v in zip(node_ids, node_ids[1:]):
            nu = nodes.get(u)
            nv = nodes.get(v)
            if not nu or not nv:
                continue
            length = haversine(nu["lat"], nu["lon"], nv["lat"], nv["lon"])
            time_s = length / max(1.0, max_speed)
            attrs = {
                "length_m": length,
                "max_speed": max_speed,
                "lanes": lanes,
                "oneway": oneway,
                "time_s": time_s,
            }
            G.add_edge(u, v, **attrs)
            if not oneway:
                G.add_edge(v, u, **attrs)
    return G


def nearest_node(G: nx.Graph, lat: float, lon: float) -> int:
    best = None
    best_d = float("inf")
    for nid, data in G.nodes(data=True):
        d = haversine(lat, lon, data.get("lat"), data.get("lon"))
        if d < best_d:
            best_d = d
            best = nid
    if best is None:
        raise ValueError("Graph has no nodes")
    return best


# =============================================================================
# PostgreSQL persistence functions
# =============================================================================


def extract_nodes_from_overpass(
    data: Dict[str, Any]
) -> List[Tuple[int, float, float]]:
    """Extract unique nodes from Overpass JSON.
    
    Args:
        data: Overpass API JSON response
        
    Returns:
        List of (osm_node_id, lat, lon) tuples
    """
    nodes = []
    seen = set()
    
    for el in data.get("elements", []):
        if el.get("type") == "node":
            osm_id = el["id"]
            if osm_id not in seen:
                nodes.append((osm_id, el["lat"], el["lon"]))
                seen.add(osm_id)
    
    log.info(f"Extracted {len(nodes)} unique nodes from Overpass data")
    return nodes


def way_to_edge(
    way: Dict[str, Any],
    nodes_dict: Dict[int, Dict[str, float]]
) -> List[Dict[str, Any]]:
    """Convert OSM way to edges.
    
    R&D-1 SIMPLIFICATION: One way = one edge (no splitting by segments).
    
    Args:
        way: OSM way dict with 'nodes', 'tags', etc.
        nodes_dict: Dict mapping osm_node_id → {"lat": ..., "lon": ...}
        
    Returns:
        List of edge dicts (1 or 2 edges if bidirectional)
    """
    tags = way.get("tags", {})
    
    # Filter: only highway roads
    if "highway" not in tags:
        return []
    
    highway_type = tags["highway"]
    
    # Skip non-drivable roads
    non_drivable = {
        "footway", "path", "steps", "pedestrian", "cycleway",
        "bridleway", "corridor", "construction"
    }
    if highway_type in non_drivable:
        return []
    
    # Parse attributes
    oneway = tags.get("oneway") in ("yes", "true", "1")
    lanes_str = str(tags.get("lanes", "1"))
    lanes = int(lanes_str) if lanes_str.isdigit() else 1
    max_speed = parse_speed(tags.get("maxspeed"))
    speed_limit_kmh = max_speed * 3.6  # m/s → km/h
    
    # Get node sequence
    node_ids = way.get("nodes", [])
    if len(node_ids) < 2:
        return []
    
    # Get coordinates
    geometry_coords = []
    for nid in node_ids:
        if nid in nodes_dict:
            node_data = nodes_dict[nid]
            geometry_coords.append([node_data["lon"], node_data["lat"]])
        else:
            # Node not in dict (shouldn't happen with Overpass 'out geom')
            log.warning(
                f"Node {nid} not found in nodes_dict "
                f"for way {way['id']}"
            )
            return []
    
    # Calculate total length
    total_length = 0.0
    for i in range(len(geometry_coords) - 1):
        lon1, lat1 = geometry_coords[i]
        lon2, lat2 = geometry_coords[i + 1]
        total_length += haversine(lat1, lon1, lat2, lon2)
    
    if total_length < 1.0:  # Skip very short edges (< 1m)
        return []
    
    # Build edge dict
    osm_way_id = way["id"]
    start_node_osm_id = node_ids[0]
    end_node_osm_id = node_ids[-1]
    
    edge = {
        "osm_way_id": osm_way_id,
        "start_node_osm_id": start_node_osm_id,
        "end_node_osm_id": end_node_osm_id,
        "geometry_coords": geometry_coords,
        "length_m": total_length,
        "speed_limit_kmh": speed_limit_kmh,
        "lanes": lanes,
        "oneway": oneway,
        "highway_type": highway_type,
        "osm_tags": tags,
    }
    
    edges = [edge]
    
    # Add reverse edge if not oneway
    if not oneway:
        reverse_edge = edge.copy()
        reverse_edge["start_node_osm_id"] = end_node_osm_id
        reverse_edge["end_node_osm_id"] = start_node_osm_id
        reverse_edge["geometry_coords"] = list(reversed(geometry_coords))
        edges.append(reverse_edge)
    
    return edges


def save_graph_to_postgres(
    overpass_data: Dict[str, Any],
    db: PostGISManager
):
    """Build graph from Overpass data and save to PostgreSQL.
    
    Args:
        overpass_data: Overpass API JSON response
        db: PostGISManager instance
    """
    log.info("Building graph from Overpass data...")
    
    # Step 1: Extract nodes
    nodes_list = extract_nodes_from_overpass(overpass_data)
    
    # Step 2: Build nodes_dict for fast lookup
    nodes_dict = {}
    for osm_id, lat, lon in nodes_list:
        nodes_dict[osm_id] = {"lat": lat, "lon": lon}
    
    # Step 3: Insert nodes to PostgreSQL
    log.info(f"Inserting {len(nodes_list)} nodes to PostgreSQL...")
    db.insert_nodes(nodes_list)
    
    # Step 4: Get node ID mapping (osm_node_id → internal id)
    osm_node_ids = [osm_id for osm_id, _, _ in nodes_list]
    node_id_map = db.get_node_ids(osm_node_ids)
    log.info(f"Mapped {len(node_id_map)} node IDs")
    
    # Step 5: Convert ways to edges
    edges = []
    elements = overpass_data.get("elements", [])
    ways = [el for el in elements if el.get("type") == "way"]
    log.info(f"Converting {len(ways)} ways to edges...")
    
    for way in ways:
        way_edges = way_to_edge(way, nodes_dict)
        for edge in way_edges:
            # Map OSM node IDs to internal IDs
            start_osm_id = edge.pop("start_node_osm_id")
            end_osm_id = edge.pop("end_node_osm_id")
            
            start_missing = start_osm_id not in node_id_map
            end_missing = end_osm_id not in node_id_map
            if start_missing or end_missing:
                log.warning(
                    f"Way {edge['osm_way_id']}: nodes not in map "
                    f"({start_osm_id}, {end_osm_id})"
                )
                continue
            
            edge["start_node_id"] = node_id_map[start_osm_id]
            edge["end_node_id"] = node_id_map[end_osm_id]
            edges.append(edge)
    
    # Step 6: Insert edges to PostgreSQL
    log.info(f"Inserting {len(edges)} edges to PostgreSQL...")
    db.insert_edges(edges)
    
    # Step 7: Get statistics
    stats = db.get_graph_stats()
    log.info(
        f"Graph build COMPLETE: "
        f"nodes={stats.get('total_nodes', 0)} "
        f"edges={stats.get('total_edges', 0)} "
        f"length={stats.get('total_length_km', 0):.2f} km"
    )
