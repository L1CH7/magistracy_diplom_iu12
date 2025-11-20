#!/bin/bash
# Test script for data-processor refactored architecture

BASE_URL="http://localhost:8005"

echo "=== Data Processor Functionality Test ==="
echo ""

# 1. Health Check
echo "[1/11] Testing /health..."
curl -s $BASE_URL/health | jq '.'
echo ""

# 2. Status API
echo "[2/11] Testing GET /api/v1/status..."
curl -s $BASE_URL/api/v1/status | jq '{tasks: .tasks.statistics, db: .database}'
echo ""

# 3. Tasks API (should be empty initially)
echo "[3/11] Testing GET /api/v1/tasks..."
TASKS_RESPONSE=$(curl -s $BASE_URL/api/v1/tasks)
echo "$TASKS_RESPONSE" | jq -r 'if type == "object" then "downloading: \(.downloading | length), saving: \(.saving | length), complete: \(.complete | length)" else "Unexpected type: \(.)" end'
echo ""

# 4. Start tile download
echo "[4/11] Testing POST /api/v1/tiles/download..."
RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/tiles/download?lon=37.5&lat=55.7&bbox_size=0.15")
echo $RESPONSE | jq '.'
TILE_KEY=$(echo $RESPONSE | jq -r '.tile_key')
echo "Tile key: $TILE_KEY"
echo ""

# 5. Check tasks during download
echo "[5/11] Checking tasks (should show downloading/saving)..."
sleep 5
curl -s $BASE_URL/api/v1/tasks | jq '{downloading: .downloading | length, saving: .saving | length}'
echo ""

# 6. Wait for download to complete
echo "[6/11] Waiting for download to complete (20s)..."
sleep 20
curl -s $BASE_URL/api/v1/status | jq '{tasks: .tasks.statistics, cached_tiles: .database.tiles_cached}'
echo ""

# 7. Get specific task details
echo "[7/11] Testing GET /api/v1/tasks/{task_id}..."
TASK_ID=$(curl -s $BASE_URL/api/v1/tasks | jq -r '.complete[0].task_id // .failed[0].task_id // "none"')
if [ "$TASK_ID" != "none" ]; then
    curl -s $BASE_URL/api/v1/tasks/$TASK_ID | jq '{task_id, phase, progress, message}'
else
    echo "No completed/failed tasks found"
fi
echo ""

# 8. Test MVT generation
echo "[8/11] Testing GET /api/v1/tiles/{z}/{x}/{y}.mvt..."
MVT_SIZE=$(curl -s $BASE_URL/api/v1/tiles/10/617/318.mvt | wc -c)
echo "MVT tile size: $MVT_SIZE bytes"
echo ""

# 9. Test redownload
echo "[9/11] Testing POST /api/v1/tiles/{tile_key}/redownload..."
if [ -n "$TILE_KEY" ]; then
    curl -s -X POST "$BASE_URL/api/v1/tiles/$TILE_KEY/redownload" | jq '.'
else
    echo "No tile_key available for redownload test"
fi
echo ""

# 10. Recovery mechanism test (restart data-processor)
echo "[10/11] Testing recovery mechanism (restart data-processor)..."
docker compose restart data-processor >/dev/null 2>&1
sleep 4
docker compose logs --tail=10 data-processor 2>&1 | grep -E "(stuck|recovered|Recovery)" || echo "No stuck tiles found (expected)"
echo ""

# 11. Final status
echo "[11/11] Final status check..."
curl -s $BASE_URL/api/v1/status | jq '.'
echo ""

echo "=== Test Complete ==="
