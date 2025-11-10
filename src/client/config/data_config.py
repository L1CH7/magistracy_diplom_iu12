"""Data fetching configuration: API endpoints, test bboxes, cache settings."""


class DataConfig:
    """Data configuration constants."""
    
    # Test bounding boxes for development
    # Format: [min_lon, min_lat, max_lon, max_lat]
    
    # Small Moscow region (for quick testing)
    TEST_BBOX_MOSCOW_SMALL = [37.5609, 55.7510, 37.6016, 55.7631]
    
    # Moscow city center
    TEST_BBOX_MOSCOW_CENTER = [37.612, 55.752, 37.622, 55.758]
    
    # Default test bbox (used by "Get Graph Data" button)
    DEFAULT_TEST_BBOX = TEST_BBOX_MOSCOW_SMALL
    
    # API timeouts (seconds)
    API_TIMEOUT_DEFAULT = 30
    API_TIMEOUT_GRAPH_FETCH = 180
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
