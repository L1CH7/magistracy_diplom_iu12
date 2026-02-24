/**
 * Marker management - creation and styling of map markers.
 */

import { getMapConfig } from './map-config-loader.js';

/**
 * Create marker element based on type and color.
 * @param {string} type - 'start'/'from', 'end'/'to', 'via', or 'agent'
 * @param {string} [color] - Custom color (for via markers)
 */
export function createMarkerElement(type, color = null) {
  const el = document.createElement('div');
  
  // Normalize type: 'from' → 'start', 'to' → 'end'
  if (type === 'from') type = 'start';
  if (type === 'to') type = 'end';
  
  const MAP_CONFIG = getMapConfig();
  if (!MAP_CONFIG) {
    console.warn('[markers] Config not loaded yet');
    return el;
  }
  
  const cfg = MAP_CONFIG.markers[type];

  if (!cfg) {
    console.warn(`Unknown marker type: ${type}`);
    return el;
  }

  el.style.width = `${cfg.size}px`;
  el.style.height = `${cfg.size}px`;
  el.style.borderRadius = '50%';
  el.style.border = `${cfg.borderWidth}px solid ${cfg.borderColor}`;

  // For via markers, use custom color; for start/end/agent use config color
  if (type === 'via' && color) {
    el.style.backgroundColor = color;
  } else {
    el.style.backgroundColor = cfg.color;
  }

  if (type === 'agent') {
    el.className = 'marker-agent';
  }

  return el;
}

/**
 * Determine marker type from point data.
 * @param {number} index - Index in points array
 * @param {number} totalPoints - Total number of points
 * @param {Object} point - Point object with display_type
 */
export function getMarkerType(index, totalPoints, point) {
  if (point.display_type) {
    return point.display_type; // Use explicit type from presenter
  }

  // Fallback to position-based detection
  if (index === 0) return 'start';
  if (index === totalPoints - 1) return 'end';
  return 'via';
}

/**
 * Get marker color from point data.
 * @param {string} type - Marker type ('start'/'from', 'end'/'to', 'via')
 * @param {Object} point - Point object with display_color/color
 */
export function getMarkerColor(type, point) {
  // Normalize type: 'from' → 'start', 'to' → 'end'
  if (type === 'from') type = 'start';
  if (type === 'to') type = 'end';
  
  if (type === 'start') {
    return point.display_color || '#2563eb';
  }
  if (type === 'end') {
    return point.display_color || '#dc2626';
  }
  if (type === 'via') {
    return point.display_color || point.color || '#8b5cf6';
  }
  
  console.warn(`Unknown marker type: ${type}`);
  const MAP_CONFIG = getMapConfig();
  return MAP_CONFIG?.markers[type]?.color || '#8b5cf6';
}
