/**
 * Agent animation - smooth movement of agent marker.
 */

import { getMapConfig } from './map-config-loader.js';
import { createMarkerElement } from './markers.js';

export class AgentAnimator {
  constructor(map) {
    this.map = map;
    this.agentCur = null;  // [lng, lat]
    this.agentTarget = null;  // [lng, lat]
    this.currentBearing = 0;  // degrees, 0=North
    this.lastFrame = 0;
    this.MAP_CONFIG = getMapConfig();  // Load config once
    
    // Create agent marker
    const el = createMarkerElement('agent');
    this.agentMarker = new maplibregl.Marker({
      element: el,
      pitchAlignment: 'map',
      rotationAlignment: 'map',
    });
  }

  updateAgent(pos) {
    // pos: { lat, lon, bearing_degrees (optional) }
    const lngLat = [pos.lon, pos.lat];
    if (!this.agentCur) {
      this.agentCur = lngLat;
    }
    this.agentTarget = lngLat;
    
    // Update bearing if provided
    if (pos.bearing_degrees !== undefined) {
      this.currentBearing = pos.bearing_degrees;
      this._rotateMarker(this.currentBearing);
    }
  }
  
  removeAgent() {
    if (this.agentMarker && this.agentMarker._map) {
      this.agentMarker.remove();
    }
    this.agentCur = null;
    this.agentTarget = null;
    console.log('Agent removed');
  }
  
  _rotateMarker(bearingDegrees) {
    if (!this.agentMarker) return;
    
    const el = this.agentMarker.getElement();
    if (!el) return;
    
    // Rotate marker to face direction of movement
    el.style.transform = `rotate(${bearingDegrees}deg)`;
  }

  animate(timestamp) {
    if (!this.agentCur || !this.agentTarget || !this.map || !this.MAP_CONFIG) {
      return;
    }

    const dt = Math.min(
      (timestamp - this.lastFrame) / 1000,
      this.MAP_CONFIG.animation.maxFrameDelta
    );
    this.lastFrame = timestamp;

    const alpha = this.MAP_CONFIG.animation.agentSmoothing;
    const next = [
      this._lerp(this.agentCur[0], this.agentTarget[0], alpha),
      this._lerp(this.agentCur[1], this.agentTarget[1], alpha),
    ];

    this.agentCur = next;
    this.agentMarker.setLngLat(next);

    if (!this.agentMarker._map) {
      this.agentMarker.addTo(this.map);
    }
  }

  _lerp(a, b, t) {
    return a + (b - a) * t;
  }
}
