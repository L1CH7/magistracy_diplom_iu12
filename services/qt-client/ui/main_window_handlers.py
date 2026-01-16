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
        
        log.info(
            "requesting_routes",
            num_points=len(points_list),
            k=k
        )
        
        # Call API (TODO: use api_client)
        import requests
        try:
            if len(points_list) >= 2:
                response = requests.post(
                    f"{self.server_url}/routing/find",
                    json={
                        "points": points_list,
                        "k": k,
                        "snap_to_edge": True,
                        "use_diversity": k > 1
                    },
                    timeout=30
                )
            else:
                # Multi-point routing not yet implemented
                log.error("multi_point_routing_not_supported")
                return
            response.raise_for_status()
            data = response.json()
            
            raw_routes = data.get("routes", [])
            log.info("routes_received", count=len(raw_routes))
            
            # Convert coordinator format → UI format
            routes = []
            for route in raw_routes:
                # Extract edge IDs
                edge_ids = route.get("edge_ids", [])
                
                # Build LineString geometry from edge geometries
                geometry_coords = []
                edges = route.get("edges", [])
                
                for edge in edges:
                    seg_geom = edge.get("geometry")
                    if seg_geom and seg_geom.get("type") == "LineString":
                        coords = seg_geom["coordinates"]
                        # Append coords, avoiding duplicates at boundaries
                        if not geometry_coords:
                            geometry_coords.extend(coords)
                        else:
                            # Skip first point if it matches last point
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
            
        except requests.exceptions.HTTPError as e:
            # Server returned error response (404, 500, etc)
            try:
                error_detail = e.response.json().get("detail", "Unknown error")
            except Exception:
                error_detail = str(e)

            log.error("get_routes_failed",
                      status_code=e.response.status_code,
                      detail=error_detail)
            
            # Show error in UI
            self.sidebar.route_panel.status_label.setText(
                f"❌ {error_detail}"
            )
            self.sidebar.route_panel.status_label.show()
            self.sidebar.route_panel.routes_list.hide()
            
        except Exception as e:
            log.error("get_routes_failed", error=str(e), exc_info=True)
            
            # Show generic error in UI
            self.sidebar.route_panel.status_label.setText(
                f"❌ Error: {str(e)}"
            )
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
            "route_data": selected_route,
            "agent_id": self.sim_agent_id
        })
        
        # Notify server if agent is running (for auto-switch logic)
        if self.sim_agent_id is not None:
            import requests
            try:
                response = requests.post(
                    f"{self.server_url}/sim/agent/{self.sim_agent_id}/consider_route",
                    params={"route_id": route_id},
                    timeout=2
                )
                response.raise_for_status()
                log.info(
                    "agent_considering_route",
                    agent_id=self.sim_agent_id,
                    route_id=route_id
                )
            except Exception as e:
                log.error("consider_route_failed", error=str(e))
    
    def _on_points_changed(self) -> None:
        """Handle points changed (added/removed) - clear routes but keep agent running."""
        log.info("points_changed_clear_routes")
        
        # DON'T stop agent - let it finish current route!
        # User can manually stop with Delete Agent button
        
        # Clear route cache on server (new points = new routes)
        import requests
        try:
            requests.post(
                f"{self.server_url}/routes/clear_cache",
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
    
    def _on_start_agent(self) -> None:
        """Handle Start Agent button click."""
        from PyQt5.QtWidgets import QMessageBox
        log.info("start_agent_clicked")
        
        # Get selected route from route panel
        routes = self.sidebar.route_panel.routes_data
        if not routes:
            log.warning("no_routes_available")
            QMessageBox.warning(
                self,
                "No Routes",
                "Please select routes first using 'Get Routes' button"
            )
            return
        
        # Use selected route (route panel stores actual route_id, not index!)
        selected_route_id = self.sidebar.route_panel.selected_route_id
        
        # Find route by ID
        route = None
        for r in routes:
            if r['id'] == selected_route_id:
                route = r
                break
        
        # Fallback to first route if not found
        if route is None:
            route = routes[0]
            log.warning("selected_route_not_found", falling_back_to_first=True)
        
        route_id = route['id']
        
        # Get simulation speed from panel
        sim_speed = self.sidebar.simulation_panel.sim_speed_spinbox.value()
        
        # Call API to start agent or restart if agent exists
        import requests
        try:
            if self.sim_agent_id is not None:
                # Agent exists - restart with selected route
                response = requests.post(
                    f"{self.server_url}/sim/agent/{self.sim_agent_id}/restart",
                    json={
                        "route_id": route_id,
                        "sim_speed": sim_speed
                    },
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                log.info("agent_restarted_with_route", route_id=route_id)
            else:
                # No agent - create new one
                response = requests.post(
                    f"{self.server_url}/sim/agent/start",
                    json={
                        "route_id": route_id,
                        "sim_speed": sim_speed
                    },
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                
                self.sim_agent_id = data['agent_id']
                log.info("agent_started", agent_id=self.sim_agent_id)
            
            # Update UI
            self.sidebar.simulation_panel.set_agent_active(True)
            self.sidebar.simulation_panel.update_agent_status(
                speed_kmh=data['speed_kmh'],
                eta_seconds=data['eta_seconds'],
                state=data['state']
            )
            
            # Start animation timer
            self._start_simulation_timer()
            
        except Exception as e:
            log.error("start_agent_failed", error=str(e))
            self.sidebar.simulation_panel.status_label.setText(
                f"Error starting agent: {str(e)}"
            )
    
    def _on_stop_agent(self) -> None:
        """Handle Stop Agent button click."""
        log.info("stop_agent_clicked")
        
        if self.sim_agent_id is None:
            return
        
        import requests
        try:
            response = requests.post(
                f"{self.server_url}/sim/agent/{self.sim_agent_id}/stop",
                timeout=5
            )
            response.raise_for_status()
            
            # Stop timer
            self._stop_simulation_timer()
            
            # Update UI
            self.sidebar.simulation_panel.update_agent_status(
                speed_kmh=0.0,
                eta_seconds=0.0,
                state="Stopped"
            )
            
            log.info("agent_stopped", agent_id=self.sim_agent_id)
            
        except Exception as e:
            log.error("stop_agent_failed", error=str(e))
    
    def _on_restart_agent(self) -> None:
        """Handle Restart Agent button click - restart with currently selected route."""
        log.info("restart_agent_clicked")
        
        if self.sim_agent_id is None:
            return
        
        # Get currently selected route (route panel stores actual route_id!)
        routes = self.sidebar.route_panel.routes_data
        if not routes:
            log.warning("no_routes_available")
            return
        
        selected_route_id = self.sidebar.route_panel.selected_route_id
        
        # Find route by ID
        route = None
        for r in routes:
            if r['id'] == selected_route_id:
                route = r
                break
        
        # Fallback to first route
        if route is None:
            route = routes[0]
            log.warning("selected_route_not_found_using_first")
        
        route_id = route['id']
        
        # Get current sim_speed
        sim_speed = self.sidebar.simulation_panel.sim_speed_spinbox.value()
        
        import requests
        try:
            response = requests.post(
                f"{self.server_url}/sim/agent/{self.sim_agent_id}/restart",
                json={
                    "route_id": route_id,
                    "sim_speed": sim_speed
                },
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            # Restart timer
            self._start_simulation_timer()
            
            # Update UI
            self.sidebar.simulation_panel.update_agent_status(
                speed_kmh=data['speed_kmh'],
                eta_seconds=data['eta_seconds'],
                state=data['state']
            )
            
            # Restore route visualization
            self._display_routes_on_map(routes)
            
            # Set selected route (blue)
            js_selected = f"""
            if (window.app && window.app.setSelectedRoute) {{
                window.app.setSelectedRoute({route_id});
            }}
            """
            self.map_widget.page().runJavaScript(js_selected)
            
            # Set assigned route (green from start - agent at beginning)
            js_assigned = f"""
            if (window.app && window.app.setAssignedRoute) {{
                window.app.setAssignedRoute({route_id}, null);
            }}
            """
            self.map_widget.page().runJavaScript(js_assigned)
            
            log.info(
                "agent_restarted",
                agent_id=self.sim_agent_id,
                route_id=route_id
            )
            
        except Exception as e:
            log.error("restart_agent_failed", error=str(e))
    
    def _update_agent_route(self, route_id: int) -> None:
        """
        Handle route selection: try mid-route rerouting (no restart).
        
        Logic:
        - User selects route (candidate) → shown as blue
        - Call /reroute: check if agent on new route edge
          - YES: agent switches reference, continues from position
          - NO: agent continues on old route reference
        - Green route = agent.assigned_route_id (not selected_id!)
        
        Start/Restart buttons will use selected_id for restart.
        """
        if self.sim_agent_id is None:
            return
        
        # Get route data
        routes = self.sidebar.route_panel.routes_data
        if route_id >= len(routes):
            return
        
        route = routes[route_id]
        route_api_id = route['id']
        
        # Get current sim_speed
        sim_speed = self.sidebar.simulation_panel.sim_speed_spinbox.value()
        
        import requests
        try:
            # Try mid-route rerouting (no restart)
            response = requests.post(
                f"{self.server_url}/sim/agent/{self.sim_agent_id}/reroute",
                json={
                    "route_id": route_api_id,
                    "sim_speed": sim_speed
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            # Update UI (no timer restart - agent continues)
            self.sidebar.simulation_panel.update_agent_status(
                speed_kmh=data['speed_kmh'],
                eta_seconds=data['eta_seconds'],
                state=data['state']
            )
            
            log.info("reroute_attempted", candidate_route_id=route_api_id)
            
        except Exception as e:
            log.error("update_agent_route_failed", error=str(e))
    
    def _on_delete_agent(self) -> None:
        """Handle Delete Agent button click."""
        log.info("delete_agent_clicked")
        
        if self.sim_agent_id is None:
            return
        
        import requests
        try:
            response = requests.delete(
                f"{self.server_url}/sim/agent/{self.sim_agent_id}",
                timeout=5
            )
            response.raise_for_status()
            
            # Stop timer
            self._stop_simulation_timer()
            
            # Remove agent from map
            js = "if (window.app && window.app.removeAgent) { window.app.removeAgent(); }"
            self.map_widget.page().runJavaScript(js)
            
            # Clear state
            self.sim_agent_id = None
            
            # Update UI
            self.sidebar.simulation_panel.set_agent_active(False)
            self.sidebar.simulation_panel.clear_agent_status()
            
            log.info("agent_deleted")
            
        except Exception as e:
            log.error("delete_agent_failed", error=str(e))
    
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
        """
        Check if agent teleported between frames.
        
        Uses ACTUAL distance traveled (from agent simulation) instead of
        haversine approximation for accurate detection.
        
        IMPORTANT: Ignores route changes and agent restarts
        """
        from services.common.utils.config_loader import config_loader
        import math
        
        config = config_loader.load('client/simulation.yaml')
        
        current_pos = (position['lon'], position['lat'])
        current_route_id = agent_data.get('assigned_route_id')
        agent_speed_kmh = agent_data.get('speed_kmh', 50.0)
        
        # Check if we should skip frames after route change
        if self._skip_teleport_frames > 0:
            self._skip_teleport_frames -= 1
            log.trace(
                "skipping_teleport_check_after_route_change",
                frames_remaining=self._skip_teleport_frames
            )
            self._prev_position = current_pos
            self._prev_route_id = current_route_id
            return
        
        # Check if route changed - if yes, skip next 3 frames
        # (large jumps expected when switching/merging routes)
        if (self._prev_route_id is not None and
                current_route_id != self._prev_route_id):
            log.info(
                "route_changed_skipping_teleport_check",
                prev_route=self._prev_route_id,
                new_route=current_route_id
            )
            self._skip_teleport_frames = 3  # Skip next 3 frames
            self._prev_position = current_pos
            self._prev_route_id = current_route_id
            return
        
        # Skip check if agent just started (speed low)
        # This handles restart on same route_id
        # Agent accelerates from 0 to ~50 km/h in first 5% of route
        if agent_speed_kmh < 10.0:  # Agent starting/accelerating
            log.trace(
                "agent_starting_skipping_teleport_check",
                speed_kmh=agent_speed_kmh
            )
            self._skip_teleport_frames = 3  # Skip next 3 frames too
            self._prev_position = current_pos
            self._prev_route_id = current_route_id
            return
        
        if self._prev_position is not None:
            # Use ACTUAL distance from agent simulation
            # (more accurate than haversine for curved routes)
            distance_m = distance_delta_m
            
            # Calculate expected distance based on ACTUAL agent speed
            sim_speed = (
                self.sidebar.simulation_panel.sim_speed_spinbox.value()
            )
            fps = self.sim_fps
            
            # Use ACTUAL agent speed (already extracted above)
            v_agent_mps = agent_speed_kmh / 3.6  # Convert to m/s
            
            # Calculate time between frames
            dt_real = 1.0 / fps  # Real-world time between frames (seconds)
            dt_sim = dt_real * sim_speed  # Simulation time between frames
            
            # Calculate maximum expected distance
            # Agent moves at v_agent speed for dt_sim seconds
            dS_expected = v_agent_mps * dt_sim
            
            # Apply margin for:
            # - Speed fluctuations (acceleration/deceleration)
            # - Route merges (smooth transitions but position jumps)
            # - Numerical errors
            # - Slight position mismatches
            # Use 3x margin to cover merge transitions
            multiplier = config['teleport_detection']['threshold_multiplier']
            threshold = dS_expected * 3.0 * multiplier
            
            if distance_m > threshold:
                # TELEPORTATION DETECTED!
                log.error(
                    "🚨 TELEPORTATION_DETECTED 🚨",
                    agent_id=self.sim_agent_id,
                    distance_m=round(distance_m, 2),
                    threshold_m=round(threshold, 2),
                    dS_expected_m=round(dS_expected, 2),
                    dt_real_s=round(dt_real, 3),
                    dt_sim_s=round(dt_sim, 3),
                    sim_speed=sim_speed,
                    fps=fps,
                    prev_pos=self._prev_position,
                    current_pos=current_pos,
                    agent_state={
                        "speed_kmh": agent_data.get('speed_kmh'),
                        "route_id": agent_data.get('assigned_route_id'),
                        "state": agent_data.get('state'),
                        "is_finished": agent_data.get('is_finished'),
                        "eta_seconds": agent_data.get('eta_seconds')
                    },
                    teleport_ratio=round(distance_m / threshold, 2),
                    # Critical for debugging
                    frame_time_ms=1000 / fps,
                    expected_max_distance_m=threshold
                )
                
                # Also log to console with clear marker
                print(f"\n{'='*80}")
                print(f"🚨 TELEPORTATION at {current_pos}")
                print(f"Distance: {distance_m:.2f}m (threshold: {threshold:.2f}m)")
                print(f"{'='*80}\n")
            else:
                # TRACE: Normal movement (no teleportation)
                log.trace(
                    "agent_movement_ok",
                    agent_id=self.sim_agent_id,
                    distance_m=round(distance_m, 2),
                    threshold_m=round(threshold, 2),
                    from_pos=self._prev_position,
                    to_pos=current_pos
                )
        
        # Update prev position and route ID
        self._prev_position = current_pos
        self._prev_route_id = current_route_id
    
    def _update_agent_position(self) -> None:
        """Timer callback: fetch agent position and update map."""
        if self.sim_agent_id is None:
            return
        
        import requests
        
        # TRACE: Log API call timing
        import time
        api_start = time.time()
        
        try:
            response = requests.get(
                f"{self.server_url}/sim/agent/{self.sim_agent_id}/position",
                timeout=2
            )
            response.raise_for_status()
            data = response.json()
            
            api_duration_ms = (time.time() - api_start) * 1000
            
            # Update map
            position = data['position']
            assigned_route_id = data.get('assigned_route_id', None)
            
            # TRACE: Log received position
            log.trace(
                "agent_position_received",
                agent_id=self.sim_agent_id,
                lon=position['lon'],
                lat=position['lat'],
                bearing=position['bearing_degrees'],
                speed_kmh=data.get('speed_kmh'),
                route_id=assigned_route_id,
                api_duration_ms=round(api_duration_ms, 2)
            )
            
            # Teleportation detection
            from services.common.utils.config_loader import config_loader
            sim_config = config_loader.load('client/simulation.yaml')
            if sim_config['teleport_detection']['enabled']:
                distance_delta_m = data.get('distance_delta_m', 0.0)
                self._check_teleportation(position, data, distance_delta_m)
            
            js = f"""
            if (window.app && window.app.updateAgent) {{
                window.app.updateAgent({{
                    lon: {position['lon']},
                    lat: {position['lat']},
                    bearing_degrees: {position['bearing_degrees']}
                }});
            }}
            """
            self.map_widget.page().runJavaScript(js)
            
            # Update assigned route visualization (green from agent to end)
            if assigned_route_id is not None:
                js_assigned = f"""
                if (window.app && window.app.setAssignedRoute) {{
                    window.app.setAssignedRoute(
                        {assigned_route_id},
                        [{position['lon']}, {position['lat']}]
                    );
                }}
                """
                self.map_widget.page().runJavaScript(js_assigned)
            
            # Update status panel
            self.sidebar.simulation_panel.update_agent_status(
                speed_kmh=data['speed_kmh'],
                eta_seconds=data['eta_seconds'],
                state=data['state']
            )
            
            # Stop timer if finished
            if data['is_finished']:
                self._stop_simulation_timer()
                log.info("agent_finished", agent_id=self.sim_agent_id)
                
        except Exception as e:
            log.error("update_agent_position_failed", error=str(e))
    
    def _stop_simulation_timer(self) -> None:
        """Stop animation timer."""
        if self.sim_timer:
            self.sim_timer.stop()
            log.info("simulation_timer_stopped")
