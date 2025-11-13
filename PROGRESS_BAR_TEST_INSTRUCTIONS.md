# Progress Bar Testing Instructions

## Current Status

✅ **Progress bar is implemented and working correctly**

The server sends progress updates in NDJSON format with:
- `percent`: 0-100 percentage
- `message`: Human-readable text (e.g., "Downloading tiles... 5/110 (4%)")
- `current`, `total`, `tile`: Additional context

Client displays the `message` on the "Get Road Graph" button.

## Why You Don't See Progress

The Moscow bbox `[37.32, 55.49, 37.90, 55.93]` was **cached in LAYER 1** (processed_geojson).

Our 3-layer cache system:
1. **LAYER 1** (processed_geojson): Full bbox cache - **instant return, no progress**
2. **LAYER 2** (tile cache): Individual 0.05° tiles - fast merge, no progress
3. **LAYER 3** (Overpass API): Downloads missing tiles - **shows progress bar**

When you clicked "Get Graph Data", it hit LAYER 1 and returned immediately.

## Test Progress Bar Now

I've **cleared the Moscow bbox from LAYER 1 cache**. Now when you click "Get Road Graph":

### Expected Behavior for Moscow [37.32, 55.49, 37.90, 55.93]

1. **First time** (uncached tiles):
   - Button text will change to: `⏳ Downloading tiles... 1/110 (1%)`
   - Progress will update every ~0.5 seconds
   - You'll see: `2/110 (2%)`, `3/110 (3%)`, ... `110/110 (100%)`
   - Total time: ~55 seconds (110 tiles × 0.5s delay)
   - After completion: Map displays Moscow roads

2. **Second time** (cached tiles):
   - LAYER 2 will activate (tiles are cached)
   - Button text: `⏳ Loading from cache...` (no percentage)
   - Fast return (~1-2 seconds)

## Automated Test

I created `test_progress_bar.py` that tests with an uncached bbox:

```bash
python3 test_progress_bar.py
```

**Result:**
```
⏳ PROGRESS #1: Downloading tiles... 1/9 (11%) | Percent: 11% | Tile: 54.15_37.55
⏳ PROGRESS #2: Downloading tiles... 2/9 (22%) | Percent: 22% | Tile: 54.15_37.60
⏳ PROGRESS #3: Downloading tiles... 3/9 (33%) | Percent: 33% | Tile: 54.15_37.65
...
⏳ PROGRESS #9: Downloading tiles... 9/9 (100%) | Percent: 100% | Tile: 54.25_37.65
------------------------------------------------------------
✅ COMPLETE!
   Progress updates received: 9
```

## Try It Yourself

### Option 1: Test with Moscow (cached cleanup done)

1. Open GUI client
2. Ensure `DEFAULT_TEST_BBOX = TEST_BBOX_MOSCOW` in `data_config.py`
3. Click "Get Road Graph" button
4. Watch button text change with progress: `⏳ Downloading tiles... X/110 (Y%)`

### Option 2: Test with completely uncached bbox

Edit `src/client/config/data_config.py`:

```python
# Use Tula region (different area, guaranteed uncached)
DEFAULT_TEST_BBOX = [37.55, 54.15, 37.65, 54.25]
```

Restart client, click "Get Road Graph", see progress for 9 tiles.

### Option 3: Clear all caches for fresh test

```bash
# Clear LAYER 1 (processed cache)
docker exec diplom-postgis psql -U diplom -d road_graphs -c "TRUNCATE graphs.processed_geojson;"

# Clear LAYER 2 (tile cache)
docker exec diplom-postgis psql -U diplom -d road_graphs -c "TRUNCATE osm.cached_tiles CASCADE; TRUNCATE osm.ways;"

# Restart server to clear memory
docker restart diplom-server-1
```

Then any bbox will show progress on first load.

## Manual Testing with curl

Test progress with a small uncached bbox:

```bash
curl -s -X POST "http://localhost:8000/osm/fetch_road_graph" \
  -H "Content-Type: application/json" \
  -d '{"bbox": [38.0, 56.0, 38.1, 56.1]}' | \
  tail -1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Features: {len(d.get('geojson',{}).get('features',[]))}\")"
```

To see progress messages (not just final result):

```bash
python3 test_progress_bar.py
```

## What to Look For

### In GUI Client

- Button text changes from "Get Road Graph" to "⏳ Downloading tiles... X/Y (Z%)"
- Percentage increases from 1% to 100%
- After 100%, button shows "✅ Graph Loaded" briefly
- Map displays roads after completion

### In Console/Logs

Check client logs (`docker logs diplom-client-1`) for:
```
[INFO] Progress: Downloading tiles... 5/110 (4%)
[INFO] Progress: Downloading tiles... 6/110 (5%)
...
[INFO] Graph loaded: 27656 features
```

## Troubleshooting

### "Loaded from processed cache" immediately

- The bbox is cached in LAYER 1
- Solution: Use a different bbox or clear cache (see above)

### No progress messages in logs but download happens

- Check that `api_workers.py` has latest code with `message` field extraction
- Redeploy: `docker cp src/client/services/api_workers.py diplom-client-1:/app/src/client/services/`
- Restart: `docker restart diplom-client-1`

### Progress stuck at X%

- Server might be rate-limited by Overpass API
- Wait ~0.5s between requests
- Check server logs: `docker logs diplom-server-1 | tail -50`

## Next Steps

After confirming progress bar works:

1. ✅ **Commit progress improvements** (if satisfied)
   ```bash
   git add src/server/app.py src/client/services/api_workers.py test_progress_bar.py
   git commit -m "feat: add progress bar with percentages for large bbox downloads"
   ```

2. 📋 **Task 3**: Create branch `features/R-D-1/architecture`
3. 📋 **Task 4**: Implement pgRouting in `features/pgRouting` branch

---

**Status**: Ready for testing. Moscow bbox cleared from LAYER 1 cache. Click "Get Road Graph" to see progress bar in action!
