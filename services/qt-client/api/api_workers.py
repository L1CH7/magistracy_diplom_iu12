"""Async workers for API requests."""
import json
import requests
from PyQt5.QtCore import QThread, pyqtSignal
from loguru import logger as log
from services.common.config import config_loader


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
    
    def __init__(self, gateway_url: str, bbox: list):
        super().__init__()
        self.gateway_url = gateway_url
        self.bbox = bbox
        self._is_cancelled = False
        # Use config timeout (600s for large bbox)
        config = config_loader.load('client/data.yaml')
        self._timeout = config['api']['timeout_graph_fetch']
    
    def cancel(self):
        """Request cancellation of the fetch operation."""
        self._is_cancelled = True
    
    def run(self):
        """Execute the graph fetch request in background thread."""
        try:
            url = f"{self.gateway_url}/osm/fetch_road_graph"
            
            log.info(
                f"GraphWorker: starting request to {url}, "
                f"bbox={self.bbox}, timeout={self._timeout}s"
            )
            
            response = requests.post(
                url,
                json={"bbox": self.bbox},
                stream=True,
                timeout=self._timeout  # From config (600s for large bbox)
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
                        message = data.get("message")
                        if message:
                            self.progress.emit(message)
                        else:
                            # Fallback for old format
                            processed = data.get("processed", 0)
                            self.progress.emit(
                                f"Processing: {processed} elements"
                            )
                    
                    elif msg_type == "complete":
                        geojson = data.get("geojson")
                        total_ways = data.get("total_ways", 0)
                        is_cached = data.get("cached", False)
                        log.info(
                            f"GraphWorker: complete received, "
                            f"ways={total_ways}, geojson={geojson is not None}"
                        )
                        break  # Exit loop after receiving complete message
                    
                    elif msg_type == "error":
                        error_msg = data.get("error", "Unknown error")
                        self.error.emit(f"Server error: {error_msg}")
                        return
            
            log.info(
                f"GraphWorker: stream ended, "
                f"geojson={geojson is not None}"
            )
            
            if geojson:
                log.info(
                    f"GraphWorker: emitting finished signal, "
                    f"features={len(geojson.get('features', []))}"
                )
                self.finished.emit({
                    'geojson': geojson,
                    'total_ways': total_ways,
                    'cached': is_cached,
                    'bbox': self.bbox
                })
            else:
                log.warning("GraphWorker: no geojson, emitting error")
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
    
    def __init__(self, gateway_url: str, waypoints: list):
        super().__init__()
        self.gateway_url = gateway_url
        self.waypoints = waypoints
        self._is_cancelled = False
    
    def cancel(self):
        """Request cancellation of the fetch operation."""
        self._is_cancelled = True
    
    def run(self):
        """Execute the route fetch request in background thread."""
        try:
            url = f"{self.gateway_url}/routing/calculate"

            waypoints = [
                {"lat": wp[0], "lon": wp[1]} for wp in self.waypoints
            ]

            response = requests.post(
                url,
                json={"waypoints": waypoints, "priority": 0},
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


import asyncio
from .ws_client import DataSocketClient

class DataSocketWorker(QThread):
    """
    Worker thread for Data WebSocket.
    Runs asyncio loop for WebSocket client.
    """
    message_received = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    
    def __init__(self, gateway_url: str):
        super().__init__()
        self.gateway_url = gateway_url
        self.client = None
        self._loop = None
        
    def run(self):
        """Run the WebSocket client."""
        # Create new event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        self.client = DataSocketClient(self.gateway_url)
        # Bridge callback to Qt signal (safe across threads?)
        # emit() is thread-safe in PyQt
        self.client.on_message = self.message_received.emit
        # Hook on_connect to signal
        self.client.on_connect = self.connected.emit
        
        try:
            # self.connected.emit() - REMOVED, now emitted by client
            # connect() runs until connection closes
            self._loop.run_until_complete(self.client.connect())
        except Exception as e:
            log.error(f"DataSocketWorker error: {e}")
        finally:
            self.disconnected.emit()
            self._loop.close()
            
    def stop(self):
        """Stop the worker."""
        if self._loop and self.client and self.client.connected:
            # Schedule disconnect in the loop
            asyncio.run_coroutine_threadsafe(
                self.client.disconnect(), 
                self._loop
            )
        # Wait for thread to finish
        self.wait(2000)

    @property
    def internal_client(self):
        return self.client
