from dataclasses import dataclass
from typing import List
import networkx as nx


@dataclass
class Route:
    nodes: List[int]
    total_distance: float
    estimated_time: float


class SimpleRouteEngine:
    def __init__(self, graph: nx.DiGraph):
        self.G = graph

    def get_route(self, start_node: int, end_node: int) -> Route:
        path: List[int] = nx.shortest_path(
            self.G, start_node, end_node, weight="time_s"
        )
        total_len = 0.0
        total_time = 0.0
        for u, v in zip(path, path[1:]):
            edge = self.G[u][v]
            total_len += float(edge.get("length_m", 0.0))
            total_time += float(edge.get("time_s", 0.0))
        return Route(
            nodes=path,
            total_distance=total_len,
            estimated_time=total_time,
        )
