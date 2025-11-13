"""Data fetching configuration: API endpoints, test bboxes, cache settings."""


class DataConfig:
    """Data configuration constants."""
    
    # Test bounding boxes for development
    # Format: [min_lon, min_lat, max_lon, max_lat]
    
    # Small Moscow region (for quick testing)
    TEST_BBOX_MOSCOW_SMALL = [37.5609, 55.7510, 37.6016, 55.7631]
    
    # Moscow city center
    TEST_BBOX_MOSCOW_CENTER = [37.4, 55.5, 37.9, 55.9]
    # TEST_BBOX_MOSCOW_CENTER = [37.612, 55.752, 37.622, 55.758]
    
    # bbox в пределах МКАД +5км
    TEST_BBOX_MOSCOW = [37.32, 55.49, 37.90, 55.93]

    # Geographic boundary for cached road network
    # Roads outside this area will be downloaded automatically on-demand
    ROADS_BBOX = TEST_BBOX_MOSCOW_SMALL
    # ROADS_BBOX = TEST_BBOX_MOSCOW_CENTER
    # ROADS_BBOX = TEST_BBOX_MOSCOW  # МКАД +5км
    
    # Legacy name for backward compatibility (deprecated)
    DEFAULT_TEST_BBOX = ROADS_BBOX
    
    # API timeouts (seconds)
    API_TIMEOUT_DEFAULT = 30
    API_TIMEOUT_GRAPH_FETCH = 600  # 10 minutes for large bbox
    API_TIMEOUT_ROUTE = 60
    
    # Graph display limits
    MAX_GRAPH_EDGES_DISPLAY = 5000
    MAX_GRAPH_NODES_DISPLAY = 10000
    
    # Drivable highway types (for filtering road graph display)
    DRIVABLE_HIGHWAY_TYPES = {
        'motorway', 'motorway_link',
        'trunk', 'trunk_link',
        'primary', 'primary_link',
        'secondary', 'secondary_link',
        'tertiary', 'tertiary_link',
        'unclassified', 'residential',
        'living_street', 'service'
    }


class MapRenderConfig:
    """Map rendering configuration for vector tiles with flexible LOD."""
    
    # LOD (Level of Detail) layers configuration
    # Each layer defines: zoom range, highway types, attributes to show
    LOD_LAYERS = [
        {
            'name': 'highways',
            'minzoom': 0,
            'maxzoom': 10,
            'highways': [
                'motorway', 'motorway_link',
                'trunk', 'trunk_link',
                'primary', 'primary_link'
            ],
            'show_names': False,
            'show_refs': True,       # Show highway refs (M-11, A-107)
            'show_lanes': False,
            'show_maxspeed': False,
            'show_surface': False,
            'base_width': 1.0,
        },
        {
            'name': 'major_roads',
            'minzoom': 10,
            'maxzoom': 12,
            'highways': [
                'motorway', 'motorway_link',
                'trunk', 'trunk_link',
                'primary', 'primary_link'
            ],
            'show_names': False,
            'show_refs': True,
            'show_lanes': False,
            'show_maxspeed': False,
            'show_surface': False,
            'base_width': 1.5,
        },
        {
            'name': 'arterial_roads',
            'minzoom': 12,
            'maxzoom': 14,
            'highways': [
                'motorway', 'motorway_link',
                'trunk', 'trunk_link',
                'primary', 'primary_link',
                'secondary', 'secondary_link',
                'tertiary', 'tertiary_link'
            ],
            'show_names': True,      # Show street names
            'show_refs': True,
            'show_lanes': True,      # Show lane count
            'show_maxspeed': False,
            'show_surface': False,
            'base_width': 2.0,
        },
        {
            'name': 'all_roads',
            'minzoom': 14,
            'maxzoom': 22,
            'highways': [
                'motorway', 'motorway_link',
                'trunk', 'trunk_link',
                'primary', 'primary_link',
                'secondary', 'secondary_link',
                'tertiary', 'tertiary_link',
                'residential', 'living_street',
                'unclassified', 'service'
            ],
            'show_names': True,
            'show_refs': True,
            'show_lanes': True,
            'show_maxspeed': True,   # Show speed limit
            'show_surface': True,    # Show road surface (asphalt/concrete)
            'base_width': 2.5,
        },
    ]
    
    # Highway types by importance level (for quick filtering)
    MOTORWAY_TYPES = ['motorway', 'motorway_link']
    MAJOR_TYPES = [
        'trunk', 'trunk_link',
        'primary', 'primary_link',
        'secondary', 'secondary_link'
    ]
    MINOR_TYPES = [
        'tertiary', 'tertiary_link',
        'residential', 'living_street',
        'unclassified', 'service'
    ]
    
    # Colors by highway type (for MapLibre style)
    COLORS = {
        'motorway': '#1e40af',        # Dark blue
        'motorway_link': '#1e40af',
        'trunk': '#6200ffff',         # Purple
        'trunk_link': '#6200ffff',
        'primary': '#9c00aaff',       # Magenta
        'primary_link': '#9c00aaff',
        'secondary': '#ff5effff',     # Pink
        'secondary_link': '#ff5effff',
        'tertiary': '#ff2e2eff',      # Red-orange
        'tertiary_link': '#ff2e2eff',
        'residential': '#ff8635ff',   # Orange
        'living_street': '#ff8635ff',
        'unclassified': '#5c5c5cff',  # Gray
        'service': '#008d0cff',       # Green
        'default': '#353535ff'        # Dark gray
    }
    
    # Base width by highway type at zoom 15 (pixels)
    WIDTH_BASE = {
        'motorway': 8,
        'trunk': 7,
        'primary': 6,
        'secondary': 5,
        'tertiary': 4,
        'residential': 3,
        'living_street': 2,
        'unclassified': 2,
        'service': 2,
        'default': 2
    }
