"""Handlers package."""

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == 'MapHandler':
        from .map_handler import MapHandler
        return MapHandler
    elif name == 'ZoomControl':
        from .zoom_handler import ZoomControl
        return ZoomControl
    elif name == 'ZoomAPIHandler':
        from .map_handler import ZoomAPIHandler
        return ZoomAPIHandler
    raise AttributeError(f"module {__name__} has no attribute {name}")

__all__ = ['MapHandler', 'ZoomControl', 'ZoomAPIHandler']
