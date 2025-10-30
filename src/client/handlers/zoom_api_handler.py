"""HTTP handler for zoom API + assets serving."""
from http.server import SimpleHTTPRequestHandler
from urllib.parse import parse_qs


class ZoomAPIHandler(SimpleHTTPRequestHandler):
    """HTTP handler for zoom API + assets serving."""

    gui_instance = None  # Will be set by NavigationGUI

    def do_GET(self):
        """Handle GET requests for both API and static files."""
        # Parse URL
        path = self.path.split('?')[0]
        query_string = self.path.split('?')[1] if '?' in self.path else ''

        # Handle API endpoints
        if path == '/api/zoom':
            # Parse zoom value from query string
            params = parse_qs(query_string)
            if 'value' in params:
                try:
                    zoom_value = float(params['value'][0])
                    # Update GUI zoom slider if instance is available
                    if self.gui_instance:
                        self.gui_instance._handle_zoom_from_js(
                            zoom_value
                        )
                    # Send 200 OK
                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'OK')
                    return
                except (ValueError, IndexError):
                    self.send_response(400)
                    self.end_headers()
                    return

        # Fall back to serving static files
        super().do_GET()
