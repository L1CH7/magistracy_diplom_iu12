import json
from typing import Dict, Tuple
import requests


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_highway_query(bbox: Tuple[float, float, float, float]) -> str:
    """Build Overpass QL to fetch highway ways and traffic signals within bbox.

    bbox: (south, west, north, east)
    """
    s, w, n, e = bbox
    return f"""
    [out:json][timeout:60];
    (
      way["highway"]({s},{w},{n},{e});
      node["highway"="traffic_signals"]({s},{w},{n},{e});
    );
    (._;>;);
    out body;
    """


def fetch_overpass(query: str) -> Dict:
    r = requests.post(OVERPASS_URL, data={"data": query})
    r.raise_for_status()
    return r.json()


def save_json(data: Dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
