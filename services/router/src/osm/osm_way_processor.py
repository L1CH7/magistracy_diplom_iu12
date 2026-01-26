import math
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from loguru import logger as log
from src.osm.osrm_profile import CarProfile, get_car_profile


@dataclass
class ProcessedSegment:
    source_node: int
    target_node: int
    osm_way_id: int
    
    source_lat: float
    source_lon: float
    target_lat: float
    target_lon: float
    bearing: float
    
    highway_type: str
    speed_kmh: float
    distance_m: float
    travel_time_sec: float
    lanes: int
    oneway: bool
    reverse: bool
    
    tags: Dict[str, str]


class OSMWayProcessor:
    def __init__(self, profile: Optional[CarProfile] = None):
        self.profile = profile or get_car_profile()
    
    def process_way(
        self,
        way: Dict,
        nodes_dict: Dict[int, Tuple[float, float]]
    ) -> List[ProcessedSegment]:
        way_id = way['id']
        node_ids = way.get('nodes', [])
        tags = way.get('tags', {})
        
        if len(node_ids) < 2:
            return []
        
        highway_type = tags.get('highway')
        if not highway_type:
            return []
        
        if not self.profile.is_highway_allowed(highway_type, tags):
            return []
        
        maxspeed = self.profile.parse_maxspeed(tags.get('maxspeed'))
        lanes = self.profile.get_lane_count(tags)
        
        speed_kmh = self.profile.get_speed(
            highway_type=highway_type,
            maxspeed=maxspeed,
            service=tags.get('service'),
            surface=tags.get('surface'),
            tracktype=tags.get('tracktype'),
            smoothness=tags.get('smoothness')
        )
        
        oneway_tag = tags.get('oneway', 'no').lower()
        oneway_forward = oneway_tag in ('yes', 'true', '1')
        oneway_reverse = oneway_tag in ('-1', 'reverse')
        bidirectional = not (oneway_forward or oneway_reverse)
        
        segments = []
        for i in range(len(node_ids) - 1):
            source_id = node_ids[i]
            target_id = node_ids[i + 1]
            
            if source_id not in nodes_dict or target_id not in nodes_dict:
                continue
            
            source_lat, source_lon = nodes_dict[source_id]
            target_lat, target_lon = nodes_dict[target_id]
            
            distance_m = self._haversine_distance(source_lat, source_lon, target_lat, target_lon)
            bearing = self._calculate_bearing(source_lat, source_lon, target_lat, target_lon)
            travel_time_sec = (distance_m / 1000.0) / speed_kmh * 3600
            
            if not oneway_reverse:
                segments.append(ProcessedSegment(
                    source_node=source_id,
                    target_node=target_id,
                    osm_way_id=way_id,
                    source_lat=source_lat,
                    source_lon=source_lon,
                    target_lat=target_lat,
                    target_lon=target_lon,
                    bearing=bearing,
                    highway_type=highway_type,
                    speed_kmh=speed_kmh,
                    distance_m=distance_m,
                    travel_time_sec=travel_time_sec,
                    lanes=lanes,
                    oneway=oneway_forward,
                    reverse=False,
                    tags=tags
                ))
            
            if bidirectional or oneway_reverse:
                reverse_bearing = (bearing + 180) % 360
                segments.append(ProcessedSegment(
                    source_node=target_id,
                    target_node=source_id,
                    osm_way_id=way_id,
                    source_lat=target_lat,
                    source_lon=target_lon,
                    target_lat=source_lat,
                    target_lon=source_lon,
                    bearing=reverse_bearing,
                    highway_type=highway_type,
                    speed_kmh=speed_kmh,
                    distance_m=distance_m,
                    travel_time_sec=travel_time_sec,
                    lanes=lanes,
                    oneway=oneway_reverse,
                    reverse=True,
                    tags=tags
                ))
        
        return segments
    
    @staticmethod
    def _haversine_distance(lat1, lon1, lat2, lon2):
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    
    @staticmethod
    def _calculate_bearing(lat1, lon1, lat2, lon2):
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)
        y = math.sin(delta_lambda) * math.cos(phi2)
        x = (math.cos(phi1) * math.sin(phi2) -
             math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda))
        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360
