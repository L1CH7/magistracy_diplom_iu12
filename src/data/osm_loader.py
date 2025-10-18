import json
from typing import Tuple, Dict, Any
import requests


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def bbox_query(bbox: Tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    # Highways (roads); nodes/ways/relations
    return f"""
    [out:json][timeout:60];
    (
      node["highway"]({south},{west},{north},{east});
      way["highway"]({south},{west},{north},{east});
      relation["highway"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """.strip().format(south=south, west=west, north=north, east=east)


def fetch_osm(bbox: Tuple[float, float, float, float]) -> Dict[str, Any]:
    query = bbox_query(bbox)
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
    resp.raise_for_status()
    return resp.json()


def save_json(data: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
