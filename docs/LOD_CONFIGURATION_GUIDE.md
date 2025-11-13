# LOD Configuration Guide

## Overview

LOD (Level of Detail) system progressively shows roads based on zoom level to optimize performance and visual clarity.

## Current Implementation

### Zoom Levels

| Layer | Zoom Range | Highway Types | Purpose |
|-------|------------|--------------|---------|
| **graph-highways** | 0-10 | motorway, motorway_link | Continental/country overview |
| **graph-major** | 10-12 | + trunk, primary | Regional navigation |
| **graph-arterial** | 12-14 | + secondary, tertiary | City-level navigation |
| **graph-all** | 14+ | All road types | Street-level detail |

### Text Labels

- **graph-labels-arterial** (z12-14): Major roads only
- **graph-labels-all** (z14+): All named roads

Labels use Russian names preferentially: `['coalesce', ['get', 'name_ru'], ['get', 'name']]`

## Color Coding (14 Highway Types)

```javascript
motorway       → #1e40af (dark blue)
trunk          → #6200ffff (purple)
primary        → #9c00aaff (magenta)
secondary      → #ff00ebff (pink)
tertiary       → #ff7b00ff (red-orange)
residential    → #ffa600ff (orange)
living_street  → #ffd000ff (yellow-orange)
unclassified   → #808080ff (gray)
service        → #4caf50ff (green)
*_link types   → Same as parent type
```

## Width Scaling

Line widths interpolate by zoom level:

- **z0-10**: 0.5-2px (highways only)
- **z10-12**: 1.5-3px (major roads)
- **z12-14**: 2-5px (arterial roads)
- **z14+**: 3-8px (all roads, type-specific)

## Configuration Files

### Current Structure

1. **src/client/assets/js/map-style.js** - MapLibre style definition (4 LOD layers hardcoded)
2. **src/client/config/data_config.py** - Python LOD_LAYERS config (not used by JavaScript yet)
3. **src/client/assets/js/map-config.js** - UI config (colors, widths for old graph layer)

### Technical Details

**Sources:**
- `osm` - Raster OSM tiles (base layer)
- `graph-vector` - MVT road network from `/tiles/roads/{z}/{x}/{y}.pbf`
- `graph` - GeoJSON routes (old format, kept for compatibility)

**Font Stack:**
- Uses MapLibre demo tiles glyphs: `https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf`
- Default font when not specified in text-font

## How to Modify LOD

### Change Zoom Ranges

Edit `minzoom`/`maxzoom` in each layer:

```javascript
{
  id: 'graph-highways',
  minzoom: 0,  // ← Start showing at this zoom
  maxzoom: 10, // ← Hide after this zoom
  // ...
}
```

### Add/Remove Highway Types

Edit `filter` arrays:

```javascript
filter: [
  'in', 'highway',
  'motorway', 'motorway_link',
  'trunk', 'trunk_link',  // ← Add/remove types here
],
```

### Change Colors

Edit `line-color` match expressions:

```javascript
'line-color': [
  'match',
  ['get', 'highway'],
  'motorway', '#1e40af',  // ← Your hex color
  'trunk', '#6200ffff',
  // ...
]
```

### Adjust Line Widths

Edit interpolation stops:

```javascript
'line-width': [
  'interpolate', ['linear'], ['zoom'],
  12, 2,   // At zoom 12: 2px
  14, 5    // At zoom 14: 5px
]
```

## Deployment

After editing `map-style.js`:

```bash
docker stop diplom-client-1
docker cp src/client/assets/js/map-style.js diplom-client-1:/app/src/client/assets/js/map-style.js
docker start diplom-client-1
```

Refresh browser (Ctrl+R) to see changes.

## Known Issues

1. **LOD config in Python not used**: `data_config.py` has LOD_LAYERS but JavaScript doesn't read it
2. **No dynamic config**: Changes require editing JavaScript and redeploying
3. **Font limitation**: Only demo fonts available, no custom fonts without glyphs server

## Future Improvements

1. **Dynamic config loading**: JavaScript fetches LOD config from server API
2. **YAML configuration**: Move configs to YAML files mounted as volumes
3. **Hot reload**: Watch config changes without container restart
4. **Custom fonts**: Host own glyphs for better typography
