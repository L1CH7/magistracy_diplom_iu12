"""
Road filtering and classification for server-side processing.

NOTE: Road colors, widths, and visual styling are defined in
configs/client/map.rendering.yaml and applied on the client side.
This module only handles filtering logic.
"""

# Drivable highway types for filtering
# This matches the routing configuration and ensures we only process
# roads that can be used for navigation
DRIVABLE_HIGHWAY_TYPES = {
    # Major roads
    'motorway', 'motorway_link',
    'trunk', 'trunk_link',
    'primary', 'primary_link',
    'secondary', 'secondary_link',
    'tertiary', 'tertiary_link',
    
    # Urban/residential
    'residential',
    'living_street',
    'unclassified',
    
    # Service roads
    'service',
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
