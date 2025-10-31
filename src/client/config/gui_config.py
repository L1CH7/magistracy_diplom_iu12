"""GUI configuration: styles, colors, geometry, defaults."""


class GUIConfig:
    """GUI configuration constants."""
    
    # Window
    WINDOW_TITLE = "Navigation MAS — Fullscreen Map"
    WINDOW_WIDTH = 1400
    WINDOW_HEIGHT = 900
    
    # Sidebar
    SIDEBAR_MAX_WIDTH = 350
    SIDEBAR_MIN_WIDTH = 280
    SIDEBAR_MIN_HEIGHT = 600
    
    # Colors - Map markers
    FROM_COLOR = "#2563eb"  # Blue
    TO_COLOR = "#dc2626"    # Red
    
    # Colors - Via point palette (beautiful, non-acidic)
    VIA_COLORS = [
        "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
        "#ec4899", "#a855f7", "#0ea5e9", "#10b981"
    ]
    
    # Default coordinates (Moscow)
    DEFAULT_START_LAT = 55.751244
    DEFAULT_START_LON = 37.618423
    DEFAULT_END_LAT = 55.755826
    DEFAULT_END_LON = 37.617300
    
    # Zoom
    ZOOM_MIN = 0
    ZOOM_MAX = 19
    ZOOM_INITIAL = 12.0
    ZOOM_BUTTON_SIZE = 15
    
    # Assets server
    ASSETS_DIR = "/app/src/client/assets"
    ASSETS_PORT = 9999
    
    # Points list
    POINTS_MAX_VISIBLE = 5
    POINT_TILE_HEIGHT = 36
    
    # Map
    MAP_GRAPH_EDGES_LIMIT = 5000
    
    # Styles - Sidebar
    SIDEBAR_STYLE = (
        "QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; "
        "border-radius: 8px; }"
    )
    
    # Styles - Buttons
    BUTTON_STYLE_PRIMARY = (
        "QPushButton { background-color: #3b82f6; color: white; "
        "border: none; border-radius: 6px; padding: 8px; "
        "font-weight: bold; } "
        "QPushButton:hover { background-color: #2563eb; }"
    )
    
    BUTTON_STYLE_SUCCESS = (
        "QPushButton { background-color: #10b981; color: white; "
        "border: none; border-radius: 6px; padding: 8px; "
        "font-weight: bold; } "
        "QPushButton:hover { background-color: #059669; } "
        "QPushButton:disabled { background-color: #d1d5db; }"
    )
    
    BUTTON_STYLE_WARNING = (
        "QPushButton { background-color: #f59e0b; color: white; "
        "border: none; border-radius: 6px; padding: 8px; "
        "font-weight: bold; } "
        "QPushButton:hover { background-color: #d97706; } "
        "QPushButton:disabled { background-color: #d1d5db; }"
    )
    
    BUTTON_STYLE_DANGER = (
        "QPushButton { background-color: #ef4444; color: white; "
        "border: none; border-radius: 6px; padding: 8px; "
        "font-weight: bold; } "
        "QPushButton:hover { background-color: #dc2626; }"
    )
    
    BUTTON_STYLE_TOGGLE = (
        "QPushButton { background-color: #2563eb; color: white; "
        "border: none; border-radius: 4px; font-weight: bold; "
        "font-size: 18px; } "
        "QPushButton:hover { background-color: #1d4ed8; }"
    )
    
    # Styles - Input
    INPUT_STYLE = (
        "QLineEdit { border-radius: 4px; padding: 4px; "
        "border: 1px solid #d1d5db; }"
    )
    
    # Styles - Text areas
    TEXT_AREA_STYLE = (
        "QTextEdit { border-radius: 4px; border: 1px solid #e5e7eb; "
        "background-color: #f9fafb; font-size: 10px; }"
    )
    
    # Styles - Zoom controls
    ZOOM_BUTTON_STYLE = (
        "QPushButton { background-color: rgba(255, 255, 255, 0.8); "
        "border: 1px solid #d1d5db; border-radius: 4px; "
        "font-weight: bold; color: #374151; } "
        "QPushButton:hover { background-color: rgba(255, 255, 255, 1); }"
    )
    
    ZOOM_SLIDER_STYLE = (
        "QSlider { background-color: transparent; "
        "border: none; margin: 0px; padding: 0px; } "
        "QSlider::groove:vertical { border: none; "
        "background-color: rgba(255, 255, 255, 0.5); "
        "border-radius: 4px; width: 8px; } "
        "QSlider::handle:vertical { background: "
        "rgba(37, 99, 235, 0.9); border: none; border-radius: 6px; "
        "height: 16px; margin: 0px -4px; } "
        "QSlider::handle:vertical:hover { background: "
        "rgba(37, 99, 235, 1); }"
    )
