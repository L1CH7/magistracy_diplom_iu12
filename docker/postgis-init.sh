#!/bin/bash
# Auto-apply migrations on PostGIS startup
# This script runs all migrations from /docker-entrypoint-initdb.d in alphabetical order
# Unlike the default docker-entrypoint behavior, this runs EVERY TIME

set -e

MIGRATIONS_DIR="/docker-entrypoint-initdb.d"
DATABASE="${POSTGRES_DB:-osm}"
USER="${POSTGRES_USER:-diplom}"

echo "=== Auto-applying migrations ==="

# Wait for postgres to be ready
until pg_isready -U "$USER" -d "$DATABASE" > /dev/null 2>&1; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done

# Track applied migrations in a table
psql -U "$USER" -d "$DATABASE" <<-EOSQL
  CREATE SCHEMA IF NOT EXISTS meta;
  
  CREATE TABLE IF NOT EXISTS meta.applied_migrations (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
EOSQL

# Apply new migrations
for migration in $(ls -1 "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
  filename=$(basename "$migration")
  
  # Check if already applied
  applied=$(psql -U "$USER" -d "$DATABASE" -tAc \
    "SELECT COUNT(*) FROM meta.applied_migrations WHERE filename='$filename'")
  
  if [ "$applied" -eq "0" ]; then
    echo "Applying migration: $filename"
    psql -U "$USER" -d "$DATABASE" -f "$migration"
    
    # Mark as applied
    psql -U "$USER" -d "$DATABASE" -c \
      "INSERT INTO meta.applied_migrations (filename) VALUES ('$filename')"
    
    echo "✓ Applied: $filename"
  else
    echo "⊘ Skipped (already applied): $filename"
  fi
done

echo "=== All migrations up to date ==="
