/**
 * Agent animation - smooth movement of agent marker.
 */

import { MAP_CONFIG } from './map-config.js';
import { createMarkerElement } from './markers.js';

export class AgentAnimator {
  constructor(map) {
    this.map = map;
    this.agentCur = null;  // [lng, lat]
    this.agentTarget = null;  // [lng, lat]
    this.lastFrame = 0;
    
    // Create agent marker
    const el = createMarkerElement('agent');
    this.agentMarker = new maplibregl.Marker({
      element: el,
      pitchAlignment: 'map',
      rotationAlignment: 'map',
    });
  }

  updateAgent(pos) {
    // pos: { lat, lon }
    const lngLat = [pos.lon, pos.lat];
    if (!this.agentCur) {
      this.agentCur = lngLat;
    }
    this.agentTarget = lngLat;
  }

  animate(timestamp) {
    if (!this.agentCur || !this.agentTarget || !this.map) {
      return;
    }

    const dt = Math.min(
      (timestamp - this.lastFrame) / 1000,
      MAP_CONFIG.animation.maxFrameDelta
    );
    this.lastFrame = timestamp;

    const alpha = MAP_CONFIG.animation.agentSmoothing;
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
