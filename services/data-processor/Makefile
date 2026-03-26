# Makefile for Data Processor
# Orchestrates OSM data downloading and cleaning.

.PHONY: download clean

# Run the standalone downloader for default bboxes
download:
	docker compose run --rm data-processor python3 src/scripts/osm_direct_download.py $(ARGS)

# Force redownload of all default bboxes
download-force:
	docker compose run --rm data-processor python3 src/scripts/osm_direct_download.py --override $(ARGS)

# Import from a local PBF file
# Usage: make from-pbf PBF=../../data/pbf/file.osm.pbf
# This target dynamically mounts the host file into the container
from-pbf:
	docker compose run --rm \
		-v "$(shell realpath $(PBF))":/tmp/import.osm.pbf:ro \
		data-processor python3 src/scripts/osm_pbf_import.py --pbf /tmp/import.osm.pbf $(ARGS)

# Clean up OSM and GRAPHS data (TRUNCATE) 
# Note: uses docker exec to run psql on the database container
clean:
	docker exec -it magistracy-diplom-iu12-postgis-1 psql -U postgres -d nav_mas -c "TRUNCATE osm.ways, osm.nodes, osm.turn_restrictions, osm.cached_tiles RESTART IDENTITY CASCADE;"
	docker exec -it magistracy-diplom-iu12-postgis-1 psql -U postgres -d nav_mas -c "TRUNCATE graphs.nodes, graphs.edges, graphs.eb_nodes, graphs.eb_edges RESTART IDENTITY CASCADE;"
	@echo "OSM and Graphs schemas cleaned."
