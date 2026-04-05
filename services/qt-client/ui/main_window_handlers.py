"""Event handlers for MainWindow - separated for clarity."""
import random
import time
from functools import wraps

from loguru import logger

log = logger


def track_metric(operation_name: str):
    """Decorator to track operation duration metrics.
    
    Args:
        operation_name: Name of the operation for logging
    
    Works with both functions and methods (preserves self).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            try:
                result = func(self, *args, **kwargs)
                duration = time.time() - start_time
                log.info(
                    f"METRIC_{operation_name}",
                    duration_sec=round(duration, 3),
                    success=True
                )
                return result
            except Exception as e:
                duration = time.time() - start_time
                log.error(
                    f"METRIC_{operation_name}",
                    duration_sec=round(duration, 3),
                    success=False,
                    error=str(e)
                )
                raise
        return wrapper
    return decorator


class MainWindowHandlers:
    """Mixin class with all event handlers for MainWindow."""
    
    # Color palette for via points
    VIA_COLORS = [
        "#8b5cf6", "#06b6d4", "#14b8a6", "#f59e0b",
        "#ec4899", "#a855f7", "#0ea5e9", "#10b981",
        "#f97316", "#eab308", "#84cc16", "#22d3ee"
    ]
    
    # Teleportation detection state
    _prev_position = None  # Previous agent position (lon, lat)
    _prev_route_id = None  # Previous route ID for change detection
    _skip_teleport_frames = 0  # Skip N frames after route change/restart
    _route_selection_cache = []  # Cache of selected routes for tests
    
    def _handle_zoom_from_js(self, zoom_value: int) -> None:
        """Handle zoom change from JS via QWebChannel (signals/slots ONLY!).
        
        Called when user changes zoom with wheel/gestures.
        Updates slider to match map zoom WITHOUT calling server.
        
        NOTE: This is called VERY frequently during zoom (every frame).
        Keep minimal to avoid Qt/Chromium bridge issues.
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
                ne: bounds.getNorthEast()ec
            };
        })();
        """
        
        def callback(result):
            if result:
                sw = result['sw']
                ne = result['ne']
                log.trace("map_bounds_updated", sw=sw, ne=ne)
        
        self.map_widget.page().runJavaScript(js, callback)
    
    @track_metric("ROUTE_DELIVERY")
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
        
        if self._zoom_slider_dragging:
            return  # Prevent requests while dragging? allow for now
        
        # 1. Fetch fresh points from JS to avoid "phantom" stale state
        js = """
        (function() {
            if (!window.app || !window.app.getPickedPoints) return null;
            return window.app.getPickedPoints();
        })();
        """
        
        def on_points_received(result):
            if not result:
                log.warning("get_routes_no_points_from_js")
                return
                
            # Parse points
            points_list = []
            if result.get('start'):
                p = result['start']
                points_list.append((p['lat'], p['lon']))
            
            via_points = result.get('via', [])
            if isinstance(via_points, list):
                for p in via_points:
                    points_list.append((p['lat'], p['lon']))
            
            if result.get('end'):
                p = result['end']
                points_list.append((p['lat'], p['lon']))
            
            if len(points_list) < 2:
                log.warning("get_routes_not_enough_points", count=len(points_list))
                return

            log.info(
                "requesting_routes",
                num_points=len(points_list),
                k=k,
                priority=0
            )
            
            # 2. Cancel previous worker if running
            if hasattr(self, '_route_worker') and self._route_worker.isRunning():
                self._route_worker.cancel()
                self._route_worker.wait()
            
            # 3. Start new worker
            from api.api_workers import RouteFetchWorker
            self._route_worker = RouteFetchWorker(
                self.gateway_url, 
                points_list, 
                k=k, 
                priority=0
            )
            self._route_worker.finished.connect(self._on_routes_received)
            self._route_worker.error.connect(self._on_route_error)
            self._route_worker.start()
            
            # Show loading state
            self.sidebar.route_panel.status_label.setText("Loading...")
            self.sidebar.route_panel.status_label.show()

        self.map_widget.page().runJavaScript(js, on_points_received)
    
    def _on_routes_received(self, data: dict) -> None:
        """Handle routes received from worker."""
        try:
            raw_routes = data.get("routes", [])
            log.info("routes_received", count=len(raw_routes))
            
            # Convert internal format → UI format
            routes = []
            for route in raw_routes:
                edge_ids = route.get("edge_ids", [])
                
                # Build LineString geometry
                geometry_coords = []
                segments = route.get("segments", [])
                
                for seg in segments:
                    seg_geom = seg.get("geometry")
                    if seg_geom and seg_geom.get("type") == "LineString":
                        coords = seg_geom["coordinates"]
                        if not geometry_coords:
                            geometry_coords.extend(coords)
                        else:
                            if coords and len(coords) > 0:
                                if coords[0] == geometry_coords[-1]:
                                    geometry_coords.extend(coords[1:])
                                else:
                                    geometry_coords.extend(coords)
                
                routes.append({
                    "id": route["route_id"],
                    "edges": edge_ids,
                    "total_distance_m": route["total_distance_m"],
                    "total_time_sec": route["estimated_time_sec"],
                    "geometry": geometry_coords
                })
            
            # Display in route panel
            self.sidebar.route_panel.display_routes(routes)
            
            # Display all routes on map
            self._display_routes_on_map(routes)

        except Exception as e:
            log.error(f"Error processing routes: {e}")
            self._on_route_error(str(e))

    def _on_route_error(self, error_msg: str) -> None:
        """Handle route worker error."""
        log.error("get_routes_failed", error=error_msg)
        self.sidebar.route_panel.status_label.setText(f"❌ {error_msg}")
        self.sidebar.route_panel.status_label.show()
        self.sidebar.route_panel.routes_list.hide()
    
    @track_metric("ROUTE_SELECTION")
    def _on_route_selected(self, route_id: int) -> None:
        """Handle route selection in panel.
        
        Args:
            route_id: Actual route ID (not index!)
        """
        log.info("route_selected", route_id=route_id)
        
        # Get route data from panel
        routes = self.sidebar.route_panel.routes_data
        
        # Find route by actual ID
        selected_route = None
        for r in routes:
            if r['id'] == route_id:
                selected_route = r
                break
        
        if selected_route is None:
            log.warning("route_not_found", route_id=route_id)
            return
        
        # Highlight selected route on map (blue)
        self._highlight_route_on_map(selected_route)
        
        # Cache route selection for tests
        import time
        self._route_selection_cache.append({
            "timestamp": time.time(),
            "route_id": route_id,
            "route_data": selected_route
            #"agent_id": self.sim_agent_id
        })
    
    def _on_points_changed(self) -> None:
        """Handle points changed (added/removed) - clear routes but keep agent running."""
        log.info("points_changed_clear_routes")
        
        # DON'T stop agent - let it finish current route!
        # User can manually stop with Delete Agent button
        
        # Clear route cache on server (new points = new routes)
        import requests
        try:
            requests.post(
                f"{self.gateway_url}/routes/clear_cache",
                timeout=5
            )
            log.info("route_cache_cleared_on_server")
        except Exception as e:
            log.warning("clear_cache_failed", error=str(e))
        
        # Clear routes from panel
        self.sidebar.route_panel.clear_routes()
        
        # Clear ONLY gray/blue routes from map, keep green (assigned)
        # DON'T call clearKRoutes() - it would reset assigned route
        # Instead, just clear the features (displayRoutes with empty list)
        js = """
        if (window.app && window.app.displayRoutes) {
            window.app.displayRoutes({type: 'FeatureCollection', features: []});
        }
        """
        self.map_widget.page().runJavaScript(js)
    
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
        
        # Use new setSelectedRoute API (blue route)
        js = f"""
        if (window.app && window.app.setSelectedRoute) {{
            window.app.setSelectedRoute({route_id});
        }}
        """
        self.map_widget.page().runJavaScript(js)
        
        log.debug("route_selected", route_id=route_id)
    
    # ========================================================================
    # Simulation Handlers
    # ========================================================================
    
    def _on_start_simulation(self) -> None:
        """Handle Start Simulation button click."""
        params = self.sidebar.simulation_panel.get_sim_params()
        log.info(f"start_simulation_requested: {params}")
        # TODO: Implement START via API
    
    def _on_pause_simulation(self) -> None:
        """Handle Pause Simulation."""
        log.info("pause_simulation_requested")
        # TODO: Implement PAUSE via API
    
    def _on_stop_simulation(self) -> None:
        """Handle Stop Simulation."""
        log.info("stop_simulation_requested")
        # TODO: Implement STOP via API
        
    def _on_step_simulation(self) -> None:
        """Handle Simulation Step (manual mode)."""
        log.info("step_simulation_requested")
        # TODO: Implement STEP via API
        
    def _on_apply_simulation_settings(self, params: dict) -> None:
        """Handle settings apply (accel, fps, etc.)."""
        log.info(f"apply_simulation_settings: {params}")
        # TODO: Implement UPDATE via API
    
    def _on_clear_routes(self) -> None:
        """Handle Clear Routes button click."""
        log.info("clear_routes_clicked")
        
        # Clear routes from panel
        self.sidebar.route_panel.clear_routes()
        
        # Clear routes from map
        js = (
            "if (window.app) { "
            "window.app.displayRoutes({type: 'FeatureCollection', features: []}); "
            "}"
        )
        self.map_widget.page().runJavaScript(js)
    
    def _on_clear_all_points(self) -> None:
        """Handle Clear All Points button click."""
        log.info("clear_all_points_clicked")
        
        # Clear points from widget
        self.sidebar.selected_points_widget.update_points([])
        
        # Clear points from map
        js = (
            "if (window.app && window.app.clearAllMarkers) { "
            "window.app.clearAllMarkers(); "
            "}"
        )
        self.map_widget.page().runJavaScript(js)
    
    def _on_sim_speed_changed(self, speed: float) -> None:
        """Handle simulation speed change."""
        log.info("sim_speed_changed", speed=speed)
        
        # TODO: Update agent simulation speed via API or local timer
    
    def _on_fps_changed(self, fps: int) -> None:
        """Handle FPS change."""
        log.info("fps_changed", fps=fps)
        
        self.sim_fps = fps
        
        # Restart timer with new interval if running
        if self.sim_timer and self.sim_timer.isActive():
            self._start_simulation_timer()
    
    def _start_simulation_timer(self) -> None:
        """Start or restart animation timer."""
        # Stop existing timer
        if self.sim_timer:
            self.sim_timer.stop()
        
        # Create new timer
        from PyQt5.QtCore import QTimer
        self.sim_timer = QTimer()
        self.sim_timer.timeout.connect(self._update_agent_position)
        
        # Calculate interval from FPS (milliseconds)
        interval_ms = int(1000 / self.sim_fps)
        self.sim_timer.start(interval_ms)
        
        log.info("simulation_timer_started", fps=self.sim_fps, interval_ms=interval_ms)
    
    def save_route_cache_for_tests(
        self, filepath: str = "route_cache.json"
    ) -> None:
        """
        Save route selection cache to file for unit tests.
        
        Args:
            filepath: Path to save cache JSON
        """
        import json
        with open(filepath, 'w') as f:
            json.dump(self._route_selection_cache, f, indent=2)
        log.info(
            "route_cache_saved",
            filepath=filepath,
            selections=len(self._route_selection_cache)
        )
    
    def _check_teleportation(
        self,
        position: dict,
        agent_data: dict,
        distance_delta_m: float
    ) -> None:
        pass
    
    def _update_agent_position(self) -> None:
        pass
    
    def _start_simulation_timer(self) -> None:
        pass

    async def _on_data_processor_connected(self):
        """Called when connected to data processor WebSocket."""
        # Load and send LOD config
        try:
            from services.common.config import config_loader
            try:
                # Try to load from project config
                # Note: Client might run in different path, adjusted for common local dev structure
                import os
                config_path = "client/map.lod.yaml"
                lod_config = config_loader.load(config_path)
            except Exception:
                # Fallback to direct file read if config_loader fails (e.g. strict paths)
                import yaml
                with open("configs/client/map.lod.yaml") as f:
                    lod_config = yaml.safe_load(f)
            
            if lod_config:
                log.info("Sending LOD config to Data Processor...")
                if self.data_msg_worker and self.data_msg_worker.internal_client:
                   # This must be run in the worker's loop or use run_coroutine_threadsafe
                   # But internal_client.send_lod_config is async.
                   # Since we are in a separate thread (created in main_window.py lambda),
                   # we can't easily await it if it belongs to another loop.
                   
                   # Actually, DataSocketWorker runs its own loop.
                   # We should schedule the send on THAT loop.
                   client = self.data_msg_worker.internal_client
                   loop = self.data_msg_worker._loop
                   if client and loop:
                       import asyncio
                       future = asyncio.run_coroutine_threadsafe(
                           client.send_lod_config(lod_config),
                           loop
                       )
                       # Wait for result if needed, or just let it fly
                       try:
                           future.result(timeout=5)
                       except Exception as e:
                           log.error(f"Failed to send config future: {e}")
                
        except Exception as e:
            log.warning(f"Failed to load/send LOD config: {e}") 

