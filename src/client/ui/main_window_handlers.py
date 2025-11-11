"""Event handlers for MainWindow - separated for clarity."""
import random

from src.utils.logging_config import get_logger

log = get_logger(__name__)


class MainWindowHandlers:
    """Mixin class with all event handlers for MainWindow."""
    
    # Color palette for via points
    VIA_COLORS = [
        "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
        "#ec4899", "#a855f7", "#0ea5e9", "#10b981",
        "#f97316", "#eab308", "#84cc16", "#22d3ee"
    ]
    
    def _handle_zoom_from_js(self, zoom_value: int) -> None:
        """Handle zoom change from JS via QWebChannel (signals/slots ONLY!).
        
        Called when user changes zoom with wheel/gestures.
        Updates slider to match map zoom WITHOUT calling server.
        """
        if self._zoom_slider_dragging:
            return  # User is dragging slider, don't update it
        
        try:
            # Convert zoom level (0-19) to slider position (0-100)
            zoom_min = 0
            zoom_max = 19
            normalized = (zoom_value - zoom_min) / (zoom_max - zoom_min)
            slider_pos = int(round((normalized ** (1.0 / 1.3)) * 100))
            slider_pos = max(0, min(100, slider_pos))
            
            # Update slider without triggering sliderMoved signal
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(slider_pos)
            self.zoom_slider.blockSignals(False)
            
            log.debug(
                "zoom_from_js",
                zoom_level=zoom_value,
                slider_position=slider_pos
            )
            
            # Update bounds when zoom changes
            self._update_map_bounds()
        except Exception as e:
            log.error("zoom_sync_failed", error=str(e), exc_info=True)
    
    def _on_zoom_slider_pressed(self) -> None:
        """Mark that user is dragging zoom slider."""
        self._zoom_slider_dragging = True
    
    def _on_zoom_slider_released(self) -> None:
        """Mark that user finished dragging zoom slider."""
        self._zoom_slider_dragging = False
    
    def _on_zoom_slider_moved(self, position: int) -> None:
        """Handle zoom slider movement (user dragging)."""
        self._set_map_zoom_from_slider(position)
    
    def _on_zoom_slider_value_changed(self, position: int) -> None:
        """Handle zoom slider value change (includes clicks on track)."""
        # Only process if not dragging (dragging handled by sliderMoved)
        if not self._zoom_slider_dragging:
            self._set_map_zoom_from_slider(position)
    
    def _set_map_zoom_from_slider(self, position: int) -> None:
        """Set map zoom from slider position (instant, no animation)."""
        # Convert slider position (0-100) to zoom level (0-19)
        normalized = (position / 100.0) ** 1.3
        zoom_min = 0
        zoom_max = 19
        zoom_level = zoom_min + normalized * (zoom_max - zoom_min)
        
        log.debug(
            "slider_zoom_update",
            slider_position=position,
            zoom_level=zoom_level
        )
        
        # Update map zoom instantly via window.app.setZoom (uses _skip flag)
        js_code = f"if (window.app) {{ window.app.setZoom({zoom_level}); }}"
        self.map_widget.page().runJavaScript(js_code)
    
    def _on_zoom_in(self) -> None:
        """Zoom in button clicked."""
        log.debug("zoom_in_clicked")
        js_code = "if (window.app) { window.app.zoomIn(); }"
        self.map_widget.page().runJavaScript(js_code)
    
    def _on_zoom_out(self) -> None:
        """Zoom out button clicked."""
        log.debug("zoom_out_clicked")
        js_code = "if (window.app) { window.app.zoomOut(); }"
        self.map_widget.page().runJavaScript(js_code)
    
    def _on_ctrl_1(self) -> None:
        """Ctrl+1: Set From point at cursor position."""
        js = "(function(){ return window.lastMousePosition || null; })();"
        
        def callback(result):
            if not result:
                log.info("ctrl1_no_mouse", message="Move mouse over map first")
                return
            
            lon = result.get('lon')
            lat = result.get('lat')
            if lon is None or lat is None:
                log.warning("ctrl1_invalid_position", result=result)
                return
            
            # Generate random color for this point
            color = random.choice(self.VIA_COLORS)
            
            # Call JS to set From point with color
            js_set = f"""
            (function() {{
                if (window.app && window.app.setStart) {{
                    window.app.setStart({{
                        lon: {lon}, lat: {lat}, color: '{color}'
                    }});
                }}
            }})();
            """
            self.map_widget.page().runJavaScript(js_set)
            
            log.info("ctrl1_from_point_set", lon=lon, lat=lat, color=color)
            self._update_selected_points()
        
        self.map_widget.page().runJavaScript(js, callback)
    
    def _on_ctrl_2(self) -> None:
        """Ctrl+2: Set To point at cursor position."""
        js = "(function(){ return window.lastMousePosition || null; })();"
        
        def callback(result):
            if not result:
                log.info("ctrl2_no_mouse", message="Move mouse over map first")
                return
            
            lon = result.get('lon')
            lat = result.get('lat')
            if lon is None or lat is None:
                log.warning("ctrl2_invalid_position", result=result)
                return
            
            # Generate random color for this point
            color = random.choice(self.VIA_COLORS)
            
            # Call JS to set To point with color
            js_set = f"""
            (function() {{
                if (window.app && window.app.setEnd) {{
                    window.app.setEnd({{
                        lon: {lon}, lat: {lat}, color: '{color}'
                    }});
                }}
            }})();
            """
            self.map_widget.page().runJavaScript(js_set)
            
            log.info("ctrl2_to_point_set", lon=lon, lat=lat, color=color)
            self._update_selected_points()
        
        self.map_widget.page().runJavaScript(js, callback)
    
    def _on_ctrl_3(self) -> None:
        """Ctrl+3: Add Via point (only if From and To exist)."""
        js = """
        (function() {
            var pos = window.lastMousePosition;
            var points = window.app && window.app.getPickedPoints
                ? window.app.getPickedPoints()
                : null;
            return {position: pos, points: points};
        })();
        """
        
        def callback(result):
            if not result or not result.get('position'):
                log.info("ctrl3_no_mouse", message="Move mouse over map first")
                return
            
            points = result.get('points', {})
            if not points.get('start') or not points.get('end'):
                log.warning(
                    "ctrl3_no_from_to",
                    message="Set From (Ctrl+1) and To (Ctrl+2) first"
                )
                return
            
            pos = result['position']
            lon = pos.get('lon')
            lat = pos.get('lat')
            if lon is None or lat is None:
                log.warning("ctrl3_invalid_position", position=pos)
                return
            
            # Pick random color
            color = random.choice(self.VIA_COLORS)
            
            # Add via marker
            js_add = (
                f"(function() {{ "
                f"if (window.app && window.app.addMarker) {{ "
                f"window.app.addMarker({{lon: {lon}, lat: {lat}}}, "
                f"'{color}'); }} }})();"
            )
            self.map_widget.page().runJavaScript(js_add)
            
            log.info("ctrl3_via_point_added", lon=lon, lat=lat, color=color)
            self._update_selected_points()
        
        self.map_widget.page().runJavaScript(js, callback)
    
    def _on_get_route(self) -> None:
        """Handle get route button click."""
        log.info("get_route_clicked")
        # TODO: implement route calculation
    
    def _on_get_road_graph(self) -> None:
        """Handle get road graph button click - async fetch from config bbox."""
        from PyQt5.QtWidgets import QMessageBox
        from src.client.services.api_workers import GraphFetchWorker
        from src.client.config import DataConfig
        
        # Get test bbox from configuration
        bbox = DataConfig.DEFAULT_TEST_BBOX
        
        log.info("=== GET_ROAD_GRAPH START (ASYNC) ===", bbox=bbox)
        
        # Disable button and show loading state
        btn = self.sidebar.get_road_graph_btn
        btn.setEnabled(False)
        self._graph_original_text = btn.text()
        btn.setText("Loading...")
        
        # Create and start background worker
        self._graph_worker = GraphFetchWorker(self.server_url, bbox)
        self._graph_worker.progress.connect(self._on_graph_progress)
        self._graph_worker.finished.connect(self._on_graph_finished)
        self._graph_worker.error.connect(self._on_graph_error)
        self._graph_worker.start()
        
        log.info("graph_worker_started", bbox=bbox)
    
    def _on_graph_progress(self, message: str) -> None:
        """Handle graph fetch progress updates."""
        btn = self.sidebar.get_road_graph_btn
        btn.setText(f"⏳ {message}")
        log.debug("graph_progress", message=message)
    
    def _on_graph_error(self, error_msg: str) -> None:
        """Handle graph fetch error."""
        from PyQt5.QtWidgets import QMessageBox
        
        log.error("graph_fetch_error", error=error_msg)
        
        # Restore button
        btn = self.sidebar.get_road_graph_btn
        btn.setText(self._graph_original_text)
        btn.setEnabled(True)
        
        # Show error to user
        QMessageBox.critical(
            self,
            "Graph Fetch Error",
            f"Failed to load road graph:\n{error_msg}"
        )
    
    def _on_graph_finished(self, data: dict) -> None:
        """Handle graph fetch completion and display on map."""
        from PyQt5.QtWidgets import QMessageBox
        from src.client.config import DataConfig
        
        geojson = data.get('geojson')
        total_ways = data.get('total_ways', 0)
        is_cached = data.get('cached', False)
        bbox = data.get('bbox')
        
        log.info(
            "graph_loaded",
            total_ways=total_ways,
            bbox=bbox,
            cached=is_cached,
            features_count=len(geojson.get("features", [])) if geojson else 0
        )
        
        # Restore button
        btn = self.sidebar.get_road_graph_btn
        btn.setText(self._graph_original_text)
        btn.setEnabled(True)
        
        # Display graph on map (already processed by server)
        if geojson:
            log.info(
                "graph_display",
                features=len(geojson.get("features", [])),
                processed_by_server=True
            )
            
            # Display on map (GeoJSON already processed by server)
            import json
            js_code = f"""
            (function() {{
                console.log('[GRAPH] Setting graph GeoJSON...');
                if (window.app && window.app.setGraphGeoJSON) {{
                    window.app.setGraphGeoJSON({json.dumps(geojson)});
                    console.log('[GRAPH] GeoJSON set, fitting...');
                    window.app.fitToGraph();
                    console.log('[GRAPH] Done!');
                }} else {{
                    console.error('[GRAPH] window.app not found!');
                }}
            }})();
            """
            
            self.map_widget.page().runJavaScript(js_code)
            
            # Show success message
            cache_msg = " (from cache)" if is_cached else ""
            QMessageBox.information(
                self,
                "Graph Loaded",
                f"Loaded {total_ways} road ways{cache_msg}"
            )
        else:
            log.warning("graph_no_data")
            QMessageBox.warning(
                self,
                "No Data",
                "No graph data received from server"
            )
    
    def _update_selected_points(self) -> None:
        """Update selected points display in sidebar."""
        # Skip sync if widget just made a change
        if (hasattr(self, '_skip_points_sync_count') and
                self._skip_points_sync_count > 0):
            self._skip_points_sync_count -= 1
            log.debug(
                "points_sync_skipped",
                remaining=self._skip_points_sync_count
            )
            return
        
        js = """
        (function() {
            if (!window.app || !window.app.getPickedPoints) {
                return null;
            }
            return window.app.getPickedPoints();
        })();
        """
        
        def callback(result):
            if result and hasattr(self.sidebar, 'selected_points_widget'):
                points = []
                # Собираем точки в правильном порядке: From, Via, To
                if result.get('start'):
                    points.append(result['start'])
                
                # Добавляем via points
                via_points = result.get('via', [])
                if isinstance(via_points, list):
                    points.extend(via_points)
                
                if result.get('end'):
                    points.append(result['end'])
                
                # Update presenter with raw points
                self.points_presenter.set_points(points)
                
                # Update widgets with styled points
                styled = self.points_presenter.get_styled_points()
                self.sidebar.selected_points_widget.update_points(styled)
                
                log.debug(
                    "selected_points_updated",
                    total=len(points),
                    via_count=len(via_points)
                )
                
                # Also update bounds when points change
                self._update_map_bounds()
        
        self.map_widget.page().runJavaScript(js, callback)
    
    def _update_map_bounds(self) -> None:
        """Update map bounds display in sidebar."""
        js = """
        (function() {
            if (!window.map || !window.map.getBounds) {
                return null;
            }
            var bounds = window.map.getBounds();
            if (!bounds) return null;
            return {
                sw: bounds.getSouthWest(),
                ne: bounds.getNorthEast()
            };
        })();
        """
        
        def callback(result):
            if result:
                sw = result['sw']
                ne = result['ne']
                bounds_text = (
                    f"SW: {sw['lng']:.4f}, {sw['lat']:.4f}\n"
                    f"NE: {ne['lng']:.4f}, {ne['lat']:.4f}"
                )
                self.sidebar.bounds_label.setText(bounds_text)
                log.debug("map_bounds_updated", sw=sw, ne=ne)
        
        self.map_widget.page().runJavaScript(js, callback)
    
    def _on_get_k_routes(self, k: int) -> None:
        """Handle Get K Routes button click.
        
        Args:
            k: Number of routes to request
        """
        log.info("get_k_routes_requested", k=k)
        
        # Get points from presenter
        points = self.points_presenter.get_raw_points()
        
        if not points:
            log.warning("no_points_set")
            return
        
        # Convert to API format
        points_list = []
        for point in points:
            points_list.append({
                "lat": point["lat"],
                "lon": point["lon"]
            })
        
        log.info(
            "requesting_routes",
            num_points=len(points_list),
            k=k
        )
        
        # Call API (TODO: use api_client)
        import requests
        try:
            response = requests.post(
                f"{self.server_url}/routes",
                json={
                    "points": points_list,
                    "k": k,
                    "snap_k": 5
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            routes = data.get("routes", [])
            log.info("routes_received", count=len(routes))
            
            # Display in route panel
            self.sidebar.route_panel.display_routes(routes)
            
            # Display all routes on map
            self._display_routes_on_map(routes)
            
        except Exception as e:
            log.error("get_routes_failed", error=str(e), exc_info=True)
    
    def _on_route_selected(self, route_id: int) -> None:
        """Handle route selection in panel.
        
        Args:
            route_id: Selected route ID
        """
        log.info("route_selected", route_id=route_id)
        
        # Get route data from panel
        routes = self.sidebar.route_panel.routes_data
        if route_id >= len(routes):
            log.warning("invalid_route_id", route_id=route_id)
            return
        
        selected_route = routes[route_id]
        
        # Highlight selected route on map
        self._highlight_route_on_map(selected_route)
    
    def _display_routes_on_map(self, routes: list) -> None:
        """Display all K routes on map (inactive state).
        
        Args:
            routes: List of route dicts with geometry
        """
        if not routes:
            return
        
        # Build GeoJSON FeatureCollection
        features = []
        for route in routes:
            geometry_coords = route.get("geometry", [])
            if not geometry_coords:
                continue
            
            feature = {
                "type": "Feature",
                "properties": {
                    "route_id": route["id"],
                    "distance_m": route["total_distance_m"],
                    "time_sec": route["total_time_sec"]
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": geometry_coords
                }
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        # Send to map
        import json
        geojson_str = json.dumps(geojson)
        js = f"""
        if (window.app && window.app.displayRoutes) {{
            window.app.displayRoutes({geojson_str});
        }}
        """
        self.map_widget.page().runJavaScript(js)
        
        log.debug("routes_displayed_on_map", count=len(routes))
    
    def _highlight_route_on_map(self, route: dict) -> None:
        """Highlight selected route on map.
        
        Args:
            route: Route dict with geometry
        """
        route_id = route["id"]
        
        js = f"""
        if (window.app && window.app.highlightRoute) {{
            window.app.highlightRoute({route_id});
        }}
        """
        self.map_widget.page().runJavaScript(js)
        
        log.debug("route_highlighted", route_id=route_id)
