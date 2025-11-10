"""Asynchronous API worker for non-blocking network requests."""

from PyQt5.QtCore import QThread, pyqtSignal
import requests
import json


class GraphFetchWorker(QThread):
    """Worker thread for fetching road graph data asynchronously.
    
    Signals:
        progress(str): Progress message
        finished(dict): Complete graph data
        error(str): Error message
    """
    
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, server_url: str, bbox: list):
        super().__init__()
        self.server_url = server_url
        self.bbox = bbox
        self._is_cancelled = False
    
    def cancel(self):
        """Request cancellation of the fetch operation."""
        self._is_cancelled = True
    
    def run(self):
        """Execute the graph fetch request in background thread."""
        try:
            url = f"{self.server_url}/osm/fetch_road_graph"
            
            response = requests.post(
                url,
                json={"bbox": self.bbox},
                stream=True,
                timeout=180
            )
            response.raise_for_status()
            
            geojson = None
            total_ways = 0
            is_cached = False
            
            # Parse NDJSON stream
            for line in response.iter_lines():
                if self._is_cancelled:
                    return
                
                if line:
                    data = json.loads(line.decode('utf-8'))
                    msg_type = data.get("type")
                    
                    if msg_type == "info":
                        message = data.get("message", "")
                        self.progress.emit(message)
                    
                    elif msg_type == "progress":
                        processed = data.get("processed", 0)
                        self.progress.emit(f"Processing: {processed} elements")
                    
                    elif msg_type == "complete":
                        geojson = data.get("geojson")
                        total_ways = data.get("total_ways", 0)
                        is_cached = data.get("cached", False)
                    
                    elif msg_type == "error":
                        error_msg = data.get("error", "Unknown error")
                        self.error.emit(f"Server error: {error_msg}")
                        return
            
            if geojson:
                self.finished.emit({
                    'geojson': geojson,
                    'total_ways': total_ways,
                    'cached': is_cached,
                    'bbox': self.bbox
                })
            else:
                self.error.emit("No data received from server")
        
        except requests.exceptions.Timeout:
            self.error.emit(
                "Request timeout - server took too long to respond"
            )
        except requests.exceptions.ConnectionError:
            self.error.emit("Connection failed - is server running?")
        except requests.exceptions.HTTPError as e:
            self.error.emit(f"HTTP error: {e}")
        except Exception as e:
            self.error.emit(f"Unexpected error: {str(e)}")


class RouteFetchWorker(QThread):
    """Worker thread for fetching route data asynchronously.
    
    Signals:
        finished(dict): Route data
        error(str): Error message
    """
    
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, server_url: str, waypoints: list):
        super().__init__()
        self.server_url = server_url
        self.waypoints = waypoints
        self._is_cancelled = False
    
    def cancel(self):
        """Request cancellation of the fetch operation."""
        self._is_cancelled = True
    
    def run(self):
        """Execute the route fetch request in background thread."""
        try:
            url = f"{self.server_url}/route/calculate"
            
            response = requests.post(
                url,
                json={"waypoints": self.waypoints},
                timeout=60
            )
            response.raise_for_status()
            
            if self._is_cancelled:
                return
            
            data = response.json()
            self.finished.emit(data)
        
        except requests.exceptions.Timeout:
            self.error.emit("Route calculation timeout")
        except requests.exceptions.ConnectionError:
            self.error.emit("Connection failed")
        except requests.exceptions.HTTPError as e:
            self.error.emit(f"HTTP error: {e}")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")
