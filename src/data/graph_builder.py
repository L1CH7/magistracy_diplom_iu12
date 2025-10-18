from typing import Dict, Any
import math
import networkx as nx


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
    return int(best)
