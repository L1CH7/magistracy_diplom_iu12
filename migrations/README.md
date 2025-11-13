# Database Migrations

Порядок применения миграций для развертывания проекта:

## 1. Initial Setup
```bash
# Create database
docker exec diplom-postgis psql -U diplom -c "CREATE DATABASE road_graphs;"

# Enable PostGIS extension
docker exec diplom-postgis psql -U diplom -d road_graphs -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

## 2. Apply Migrations

```bash
# Run migrations in order
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/001_init_osm_schema.sql
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/002_add_processed_geojson_cache.sql
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/003_create_graph_tables.sql
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/004_add_geom_3857_for_mvt.sql
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/004_add_bearing_to_edges.sql
docker exec -i diplom-postgis psql -U diplom -d road_graphs < migrations/005_add_turn_restrictions.sql
```

## Migration Details

### 001_init_osm_schema.sql
- Creates `osm` schema
- Creates tables: `ways`, `nodes`, `cached_tiles`, `regions`
- Creates spatial indexes (GIST)
- Creates helper functions for tile caching

### 002_add_processed_geojson_cache.sql
- Creates `graphs.processed_geojson` table
- Stores filtered/processed GeoJSON for fast retrieval

### 003_create_graph_tables.sql
- Creates `graphs.nodes` and `graphs.edges` tables
- Routing graph storage

### 004_add_geom_3857_for_mvt.sql
- Adds `geom_3857` column to `osm.ways`
- Creates trigger for automatic Web Mercator conversion
- Enables efficient MVT (Mapbox Vector Tiles) generation

### 004_add_bearing_to_edges.sql
- Adds bearing calculation to graph edges

### 005_add_turn_restrictions.sql
- Adds turn restrictions support for routing

## Verification

```bash
# Check schema
docker exec diplom-postgis psql -U diplom -d road_graphs -c "\dt osm.*"
docker exec diplom-postgis psql -U diplom -d road_graphs -c "\dt graphs.*"

# Check row counts
docker exec diplom-postgis psql -U diplom -d road_graphs -c "
SELECT 'osm.ways' as table, COUNT(*) FROM osm.ways
UNION ALL
SELECT 'osm.cached_tiles', COUNT(*) FROM osm.cached_tiles
UNION ALL
SELECT 'graphs.processed_geojson', COUNT(*) FROM graphs.processed_geojson;
"
```

## Notes

- All migrations are idempotent (can be run multiple times safely)
- Use `IF NOT EXISTS` and `ON CONFLICT` where appropriate
- Large data migrations (like `geom_3857` backfill) use batching
