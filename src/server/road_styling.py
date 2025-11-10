"""
Road styling and classification for rendering.
Defines colors, widths, and lane configurations for different road types.
"""

# Road classification by highway type
ROAD_CLASSES = {
    # Motorways (Автомагистрали)
    'motorway': {
        'color': '#e892a2',  # Pink
        'width': 8,
        'priority': 1,
        'drivable': True,
        'default_lanes': 4,
        'default_maxspeed': 110,
    },
    'motorway_link': {
        'color': '#e892a2',
        'width': 6,
        'priority': 2,
        'drivable': True,
        'default_lanes': 2,
        'default_maxspeed': 70,
    },
    
    # Trunk roads (Скоростные дороги)
    'trunk': {
        'color': '#f9b29c',  # Light orange
        'width': 7,
        'priority': 3,
        'drivable': True,
        'default_lanes': 4,
        'default_maxspeed': 90,
    },
    'trunk_link': {
        'color': '#f9b29c',
        'width': 5,
        'priority': 4,
        'drivable': True,
        'default_lanes': 2,
        'default_maxspeed': 60,
    },
    
    # Primary roads (Главные дороги)
    'primary': {
        'color': '#fcd6a4',  # Pale orange
        'width': 6,
        'priority': 5,
        'drivable': True,
        'default_lanes': 3,
        'default_maxspeed': 70,
    },
    'primary_link': {
        'color': '#fcd6a4',
        'width': 4,
        'priority': 6,
        'drivable': True,
        'default_lanes': 2,
        'default_maxspeed': 50,
    },
    
    # Secondary roads (Второстепенные дороги)
    'secondary': {
        'color': '#f7fabf',  # Pale yellow
        'width': 5,
        'priority': 7,
        'drivable': True,
        'default_lanes': 2,
        'default_maxspeed': 60,
    },
    'secondary_link': {
        'color': '#f7fabf',
        'width': 3,
        'priority': 8,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 40,
    },
    
    # Tertiary roads (Третьестепенные дороги)
    'tertiary': {
        'color': '#ffffff',  # White
        'width': 4,
        'priority': 9,
        'drivable': True,
        'default_lanes': 2,
        'default_maxspeed': 50,
    },
    'tertiary_link': {
        'color': '#ffffff',
        'width': 3,
        'priority': 10,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 30,
    },
    
    # Residential/urban streets (Жилые улицы)
    'residential': {
        'color': '#ffffff',  # White
        'width': 3,
        'priority': 11,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 30,
    },
    'living_street': {
        'color': '#ededed',  # Light grey
        'width': 2,
        'priority': 12,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 20,
    },
    'unclassified': {
        'color': '#ffffff',
        'width': 3,
        'priority': 13,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 50,
    },
    
    # Service roads (Служебные дороги)
    'service': {
        'color': '#cccccc',  # Grey
        'width': 2,
        'priority': 14,
        'drivable': True,
        'default_lanes': 1,
        'default_maxspeed': 20,
    },
    
    # Non-drivable (for reference)
    'pedestrian': {
        'color': '#dddde8',
        'width': 2,
        'priority': 20,
        'drivable': False,
    },
    'footway': {
        'color': '#fa8072',
        'width': 1,
        'priority': 21,
        'drivable': False,
    },
    'cycleway': {
        'color': '#0000ff',
        'width': 1,
        'priority': 22,
        'drivable': False,
    },
    'path': {
        'color': '#2f4f4f',
        'width': 1,
        'priority': 23,
        'drivable': False,
    },
    'steps': {
        'color': '#fe9292',
        'width': 1,
        'priority': 24,
        'drivable': False,
    },
}

# Get all drivable road types
DRIVABLE_HIGHWAY_TYPES = {
    k for k, v in ROAD_CLASSES.items() if v.get('drivable', False)
}


def filter_geojson(geojson: dict, drivable_only: bool = True) -> dict:
    """
    Filter GeoJSON to drivable roads and round coordinates.
    
    Сохраняет ВСЕ OSM properties как есть для будущего использования в графе.
    Не добавляет render_* поля - раскраска делается на клиенте.
    
    Args:
        geojson: Input GeoJSON FeatureCollection
        drivable_only: If True, keep only drivable roads
        
    Returns:
        Filtered GeoJSON with rounded coordinates
    """
    if not geojson or not geojson.get('features'):
        return geojson
    
    filtered_features = []
    
    for feature in geojson['features']:
        properties = feature.get('properties', {})
        highway_type = properties.get('highway')
        
        if not highway_type:
            continue
        
        # Filter to drivable roads only
        if drivable_only and highway_type not in DRIVABLE_HIGHWAY_TYPES:
            continue
        
        # Round coordinates to 6 decimals (~11cm precision)
        coords = feature['geometry']['coordinates']
        feature['geometry']['coordinates'] = [
            [round(lon, 6), round(lat, 6)] for lon, lat in coords
        ]
        
        # Сохраняем ВСЕ OSM properties как есть - они понадобятся для графа
        filtered_features.append(feature)
    
    return {
        'type': 'FeatureCollection',
        'features': filtered_features
    }


def generate_lane_geometry(feature: dict) -> list:
    """
    Generate individual lane geometries from road centerline.
    
    For a road with N lanes, generates N parallel lines offset from centerline.
    Includes shoulder/emergency lanes if specified.
    
    Args:
        feature: GeoJSON feature with road geometry
        
    Returns:
        list of lane features with geometry and properties:
        - lane_index: 0-based lane number
        - lane_type: 'regular', 'bus', 'emergency', 'shoulder'
        - marking_left: 'solid', 'dashed', 'none'
        - marking_right: 'solid', 'dashed', 'none'
    """
    # TODO: Implement lane geometry generation
    # This requires:
    # 1. Calculate perpendicular offset vectors along road centerline
    # 2. Generate parallel LineStrings for each lane
    # 3. Determine lane markings based on position and road rules
    # 4. Handle bus lanes, emergency lanes from OSM tags
    #    (e.g., lanes:bus, lanes:emergency)
    
    # For now, return empty list (will implement in next iteration)
    return []
