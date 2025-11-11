"""Graph class for routing with adjacency list optimization.

Loads graph from PostgreSQL and provides O(1) neighbor access.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from src.data.postgis_manager import PostGISManager
from src.utils.logger import setup_logger

log = setup_logger(__name__)


@dataclass
class Node:
    """Graph node (intersection or endpoint)."""
    id: int
    osm_node_id: int
    lat: float
    lon: float


@dataclass
class Edge:
    """Represents a road edge in the graph."""
    id: int
    osm_way_id: int
    start_node_id: int
    end_node_id: int
    length_m: float
    speed_limit_kmh: float
    lanes: int
    oneway: bool
    highway_type: str
    capacity: int
    base_travel_time_sec: float
    bearing: Optional[float] = None  # Edge bearing in degrees (0-360)
    current_load: int = 0
    effective_speed_kmh: Optional[float] = None
    
    def get_travel_time(self) -> float:
        """Get current travel time considering congestion."""
        if self.effective_speed_kmh and self.effective_speed_kmh > 0:
            return self.length_m / (self.effective_speed_kmh / 3.6)
        return self.base_travel_time_sec
    
    def get_congestion_ratio(self) -> float:
        """Get current congestion ratio [0..1+]."""
        if self.capacity > 0:
            return self.current_load / self.capacity
        return 0.0


class Graph:
    """Road network graph with fast neighbor access."""
    
    def __init__(self):
        """Initialize empty graph."""
        self.nodes: Dict[int, Node] = {}
        self.edges: Dict[int, Edge] = {}
        self.adjacency_list: Dict[int, List[int]] = defaultdict(list)
        self._loaded = False
    
    @classmethod
    def load_from_db(cls, db: PostGISManager) -> 'Graph':
        """Load full graph from PostgreSQL.
        
        Args:
            db: PostGISManager instance
            
        Returns:
            Loaded Graph instance
        """
        graph = cls()
        
        log.info("Loading graph from database")
        nodes_data, edges_data = db.load_full_graph()
        
        # Load nodes
        for node_dict in nodes_data:
            node = Node(
                id=node_dict['id'],
                osm_node_id=node_dict['osm_node_id'],
                lat=node_dict['lat'],
                lon=node_dict['lon']
            )
            graph.nodes[node.id] = node
        
        # Load edges and build adjacency list
        for edge_dict in edges_data:
            edge = Edge(
                id=edge_dict['id'],
                osm_way_id=edge_dict['osm_way_id'],
                start_node_id=edge_dict['start_node_id'],
                end_node_id=edge_dict['end_node_id'],
                length_m=edge_dict['length_m'],
                speed_limit_kmh=edge_dict['speed_limit_kmh'],
                lanes=edge_dict['lanes'],
                oneway=edge_dict['oneway'],
                highway_type=edge_dict['highway_type'],
                capacity=edge_dict['capacity'],
                base_travel_time_sec=edge_dict['base_travel_time_sec'],
                bearing=edge_dict.get('bearing'),
                current_load=edge_dict.get('current_load', 0),
                effective_speed_kmh=edge_dict.get('effective_speed_kmh')
            )
            graph.edges[edge.id] = edge
            
            # Build adjacency list: node_id → [outgoing_edge_ids]
            graph.adjacency_list[edge.start_node_id].append(edge.id)
        
        graph._loaded = True
        log.info(
            "Graph loaded",
            nodes=len(graph.nodes),
            edges=len(graph.edges)
        )
        
        return graph
    
    def get_neighbors(self, node_id: int) -> List[Edge]:
        """Get all outgoing edges from node (O(1) access).
        
        Args:
            node_id: Node ID
            
        Returns:
            List of outgoing edges
        """
        edge_ids = self.adjacency_list.get(node_id, [])
        return [self.edges[eid] for eid in edge_ids]
    
    def get_node(self, node_id: int) -> Optional[Node]:
        """Get node by ID."""
        return self.nodes.get(node_id)
    
    def get_edge(self, edge_id: int) -> Optional[Edge]:
        """Get edge by ID."""
        return self.edges.get(edge_id)
    
    def find_nearest_nodes(
        self,
        lat: float,
        lon: float,
        k: int = 5
    ) -> List[Tuple[int, float]]:
        """Find K nearest nodes to a point.
        
        Simple Euclidean distance (for now).
        For production: use PostGIS ST_Distance.
        
        Args:
            lat: Latitude
            lon: Longitude
            k: Number of nearest nodes
            
        Returns:
            List of (node_id, distance) tuples
        """
        distances = []
        for node_id, node in self.nodes.items():
            # Euclidean distance (approximate)
            dlat = node.lat - lat
            dlon = node.lon - lon
            dist = (dlat**2 + dlon**2)**0.5
            distances.append((node_id, dist))
        
        distances.sort(key=lambda x: x[1])
        return distances[:k]
    
    def is_loaded(self) -> bool:
        """Check if graph is loaded."""
        return self._loaded
    
    def get_stats(self) -> Dict:
        """Get graph statistics."""
        return {
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'avg_degree': (
                sum(len(edges) for edges in self.adjacency_list.values())
                / len(self.adjacency_list)
                if self.adjacency_list else 0
            )
        }
