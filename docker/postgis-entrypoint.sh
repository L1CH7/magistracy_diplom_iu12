#!/bin/bash
# Custom entrypoint wrapper for PostGIS that auto-applies migrations
set -e

# Check if DB already initialized
if [ -d "/var/lib/postgresql/data/base" ]; then
  echo "=== Existing database detected ===" 
  
  # Start postgres in background to apply migrations
  docker-entrypoint.sh postgres &
  PG_PID=$!
  
  # Wait for postgres
  until pg_isready -U "${POSTGRES_USER:-diplom}" -d "${POSTGRES_DB:-osm}" > /dev/null 2>&1; do
    sleep 1
  done
  
  # Apply migrations
  /usr/local/bin/apply-migrations.sh
  
  # Keep postgres running
  wait $PG_PID
else
  # First run: let docker-entrypoint handle everything (it will apply initdb scripts)
  exec docker-entrypoint.sh postgres
fi
