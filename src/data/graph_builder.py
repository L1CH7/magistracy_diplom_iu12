"""Graph building utilities from OSM Overpass data with PostgreSQL persistence.

This module builds graphs from OSM data and saves them to PostgreSQL.
Uses OSMWayProcessor for OSRM-style way processing with turn penalties.
"""

from typing import Dict, Any, List, Tuple
import math
import networkx as nx
from src.data.postgis_manager import PostGISManager
from src.data.osm_way_processor import OSMWayProcessor, ProcessedSegment
from src.data.osrm_profile import get_car_profile
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


def segments_to_edge_dicts(
    segments: List[ProcessedSegment],
    way_id: int
) -> List[Dict[str, Any]]:
    """Convert ProcessedSegments to edge dicts for PostgreSQL.
    
    Args:
        segments: List of ProcessedSegment from OSMWayProcessor
        way_id: OSM way ID
        
    Returns:
        List of edge dicts ready for database insertion
    """
    edge_dicts = []
    
    for seg in segments:
        # Build geometry (simple 2-point line for now)
        geometry_coords = [
            [seg.source_lon, seg.source_lat],
            [seg.target_lon, seg.target_lat]
        ]
        
        edge_dict = {
            "osm_way_id": way_id,
            "start_node_osm_id": seg.source_node,
            "end_node_osm_id": seg.target_node,
            "geometry_coords": geometry_coords,
            "length_m": seg.distance_m,
            "speed_limit_kmh": seg.speed_kmh,
            "lanes": seg.lanes,
            "oneway": seg.oneway,
            "highway_type": seg.highway_type,
            "bearing": seg.bearing,
            "osm_tags": seg.tags,
        }
        edge_dicts.append(edge_dict)
    
    return edge_dicts


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
    
    # Step 5: Convert ways to edges using OSMWayProcessor
    edges = []
    elements = overpass_data.get("elements", [])
    ways = [el for el in elements if el.get("type") == "way"]
    log.info(f"Converting {len(ways)} ways to edges with OSRM profile...")
    
    # Initialize processor with OSRM profile
    profile = get_car_profile()
    processor = OSMWayProcessor(profile)
    
    # Build nodes_coords for processor: {osm_id: (lat, lon)}
    nodes_coords = {
        osm_id: (data["lat"], data["lon"])
        for osm_id, data in nodes_dict.items()
    }
    
    processed_count = 0
    for way in ways:
        # Process way with OSRM-style logic
        segments = processor.process_way(way, nodes_coords)
        
        if not segments:
            continue
        
        # Convert segments to edge dicts
        way_edges = segments_to_edge_dicts(segments, way["id"])
        processed_count += len(way_edges)
        
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
    log.info(
        f"Inserting {len(edges)} edges to PostgreSQL "
        f"(processed {processed_count} segments from {len(ways)} ways)..."
    )
    db.insert_edges(edges)
    
    # Step 7: Load turn restrictions from OSM relations
    relations = [el for el in elements if el.get("type") == "relation"]
    restriction_relations = [
        r for r in relations
        if r.get("tags", {}).get("type") == "restriction"
    ]
    
    if restriction_relations:
        log.info(
            f"Loading {len(restriction_relations)} turn restrictions..."
        )
        
        from src.data.turn_restrictions import TurnRestrictionManager
        restrictions_mgr = TurnRestrictionManager()
        restrictions_mgr.load_from_osm_relations(restriction_relations)
        
        # Convert to DB format
        restriction_dicts = []
        for r in restrictions_mgr.restrictions:
            restriction_dicts.append({
                'osm_relation_id': r.relation_id,
                'restriction_type': r.restriction_type,
                'from_way_id': r.from_way,
                'via_node_id': r.via_node,
                'to_way_id': r.to_way,
                'is_prohibitive': r.is_prohibitive,
                'is_mandatory': r.is_mandatory
            })
        
        db.insert_turn_restrictions(restriction_dicts)
    else:
        log.info("No turn restrictions found in OSM data")
    
    # Step 8: Get statistics
    stats = db.get_graph_stats()
    restr_count = (
        len(restriction_dicts) if restriction_relations else 0
    )
    log.info(
        "graph_build_complete",
        nodes=stats.get('total_nodes', 0),
        edges=stats.get('total_edges', 0),
        length_km=round(stats.get('total_length_km', 0), 2),
        avg_edge_length_m=round(stats.get('avg_edge_length_m', 0), 1),
        turn_restrictions=restr_count,
        profile_used="car"
    )


def load_graph_from_postgis(db: PostGISManager) -> nx.MultiDiGraph:
    """Load graph from PostgreSQL and convert to NetworkX.
    
    Args:
        db: PostGISManager instance
        
    Returns:
        NetworkX MultiDiGraph with node and edge attributes
    """
    log.info("Loading graph from PostgreSQL...")
    
    # Load nodes and edges from DB
    nodes, edges = db.load_full_graph()
    
    # Build NetworkX MultiDiGraph to support multiple edges
    graph = nx.MultiDiGraph()
    
    # Add nodes
    for node in nodes:
        graph.add_node(
            node['id'],
            osm_node_id=node['osm_node_id'],
            lat=node['lat'],
            lon=node['lon']
        )
    
    # Add edges
    for edge in edges:
        graph.add_edge(
            edge['start_node_id'],
            edge['end_node_id'],
            edge_id=edge['id'],
            osm_way_id=edge['osm_way_id'],
            length_m=edge['length_m'],
            speed_limit_kmh=edge['speed_limit_kmh'],
            lanes=edge['lanes'],
            oneway=edge.get('oneway', False),
            highway_type=edge['highway_type'],
            capacity=edge['capacity'],
            base_travel_time_sec=edge['base_travel_time_sec'],
            bearing=edge.get('bearing'),
            time_s=edge['base_travel_time_sec']  # For compatibility
        )
    
    log.info(
        "graph_loaded_from_postgis",
        nodes=graph.number_of_nodes(),
        edges=graph.number_of_edges()
    )
    
    return graph
