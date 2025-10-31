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
