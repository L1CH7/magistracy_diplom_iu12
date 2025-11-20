#!/bin/bash
# Retry downloading failed tile by removing from cached_tiles

TILE_KEY="$1"

if [ -z "$TILE_KEY" ]; then
    echo "Usage: $0 <tile_key>"
    echo "Example: $0 37.20_55.60"
    exit 1
fi

echo "Removing tile $TILE_KEY from cached_tiles..."
docker compose exec postgis psql -U diplom -d osm -c "DELETE FROM osm.cached_tiles WHERE tile_key = '$TILE_KEY'"

echo "Triggering tile download via API..."
LON=$(echo $TILE_KEY | cut -d'_' -f1)
LAT=$(echo $TILE_KEY | cut -d'_' -f2)

curl -s -X POST "http://localhost:8005/api/v1/data/download-tile?lon=$LON&lat=$LAT" | jq .
echo ""
echo "✓ Tile download triggered"
echo "  Check logs: docker compose logs -f data-processor"
echo "  Check status: curl -s http://localhost:8005/api/v1/data/stats | jq ."
