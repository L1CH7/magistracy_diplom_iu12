#pragma once

#include <string_view>

namespace traffic::graph_builder
{

// ============================================================================
// GRAPHS SCHEMA
// ============================================================================
constexpr std::string_view DROP_SCHEMA_SQL = R"(
DROP SCHEMA IF EXISTS graphs CASCADE;
)";

constexpr std::string_view INIT_SCHEMA_SQL = R"(
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

CREATE SCHEMA IF NOT EXISTS graphs;

CREATE TABLE IF NOT EXISTS graphs.builder_state (
    stage VARCHAR(50) PRIMARY KEY,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graphs.nodes (
    id SERIAL PRIMARY KEY,
    osm_node_id BIGINT UNIQUE NOT NULL,
    geom GEOMETRY(POINT, 4326) NOT NULL
);

CREATE TABLE graphs.edges (
    id SERIAL PRIMARY KEY,
    source_id bigint,
    target_id bigint,
    osm_way_id bigint,
    geometry geometry(LineString, 4326),
    length_m float,
    speed_limit_kmh float,
    lanes int,
    oneway int,
    highway_type text,
    osm_tags jsonb,
    max_speed float,
    duration float, 
    is_open boolean DEFAULT true,
    current_load int DEFAULT 0,
    effective_speed_kmh float DEFAULT 60.0, 
    cost float,
    reverse_cost float
);
CREATE INDEX idx_graphs_edges_source ON graphs.edges(source_id);
CREATE INDEX idx_graphs_edges_target ON graphs.edges(target_id);
CREATE INDEX idx_graphs_edges_geom ON graphs.edges USING GIST(geometry);
)";

// ============================================================================
// STAGE 1: CANDIDATES EXTRACTION
// ============================================================================
constexpr std::string_view INIT_CANDIDATES_SQL = R"(
DROP TABLE IF EXISTS edge_candidates CASCADE;
CREATE TABLE edge_candidates (
    id bigint,
    tags jsonb,
    highway text,
    maxspeed text,
    lanes int,
    oneway int,
    source int,
    target int,
    geom geometry(LineString, 4326),
    is_ground boolean
);
)";

// Batch insertion placeholder
constexpr std::string_view INSERT_CANDIDATES_BATCH_SQL = R"(
INSERT INTO edge_candidates (id, tags, highway, maxspeed, lanes, oneway, geom, is_ground)
SELECT 
    id, 
    tags, 
    tags->>'highway' as highway,
    tags->>'maxspeed' as maxspeed,
    (tags->>'lanes')::int as lanes,
    CASE 
        WHEN tags->>'oneway' = 'yes' THEN 1 
        WHEN tags->>'oneway' = '-1' THEN -1 
        ELSE 0 
    END as oneway,
    ST_SnapToGrid(
        ST_Subdivide(
            ST_Segmentize(geom::geography, 50)::geometry, 
            20
        ), 
        0.000001
    ),
    CASE 
        WHEN tags->>'bridge' IS NOT NULL THEN false
        WHEN tags->>'tunnel' IS NOT NULL THEN false
        WHEN tags->>'layer' IS NOT NULL AND tags->>'layer' != '0' THEN false
        ELSE true 
    END as is_ground
FROM osm.ways
WHERE tags ? 'highway' 
  AND tags->>'highway' IN (
      'motorway', 'motorway_link', 'trunk', 'trunk_link',
      'primary', 'primary_link', 'secondary', 'secondary_link',
      'tertiary', 'tertiary_link', 'residential', 'living_street',
      'service', 'unclassified'
  )
LIMIT {} OFFSET {};
)";

constexpr std::string_view INDEX_CANDIDATES_SQL = R"(
CREATE INDEX idx_ec_geom ON edge_candidates USING GIST(geom);
CREATE INDEX idx_edge_candidates_id ON edge_candidates(id);
CREATE INDEX idx_ec_is_ground ON edge_candidates(is_ground);
ANALYZE edge_candidates;
)";

// ============================================================================
// STAGE 2: GRID NODING
// ============================================================================
constexpr std::string_view INIT_MERGED_SQL = R"(
DROP TABLE IF EXISTS edge_candidates_merged CASCADE;
CREATE TABLE edge_candidates_merged (
    id SERIAL PRIMARY KEY,
    old_id bigint,
    sub_id int DEFAULT 1,
    source int,
    target int,
    geom geometry(LineString, 4326)
);
CREATE INDEX idx_ecm_geom ON edge_candidates_merged USING GIST(geom);
)";

// We use format to fill box strings
constexpr std::string_view GRID_NODING_TILE_SQL = R"(
WITH 
selection AS (
    SELECT id, geom FROM edge_candidates 
    WHERE is_ground = TRUE AND geom && ST_Expand(ST_MakeEnvelope({0}, {1}, {2}, {3}, 4326), 0.001)
),
noded_geoms AS (
    SELECT (ST_Dump(ST_Node(ST_Collect(geom)))).geom as geom 
    FROM selection
),
valid_segments AS (
    SELECT geom FROM noded_geoms
    WHERE ST_Contains(ST_MakeEnvelope({0}, {1}, {2}, {3}, 4326), ST_Centroid(geom))
)
INSERT INTO edge_candidates_merged (old_id, geom)
SELECT DISTINCT ON (s.geom)
    e.id, 
    s.geom
FROM valid_segments s
JOIN selection e ON ST_DWithin(s.geom, e.geom, 0.000001) AND ST_CoveredBy(s.geom, e.geom);
)";

constexpr std::string_view COPY_BRIDGES_SQL = R"(
INSERT INTO edge_candidates_merged (old_id, geom)
SELECT id, geom FROM edge_candidates WHERE is_ground = FALSE;
)";

constexpr std::string_view INDEX_MERGED_SQL = R"(
CREATE INDEX IF NOT EXISTS idx_ecm_old_id ON edge_candidates_merged(old_id);
ANALYZE edge_candidates_merged;
)";

// ============================================================================
// STAGE 3: CREATE TOPOLOGY & POPULATE
// ============================================================================
constexpr std::string_view CREATE_TOPOLOGY_SQL = R"(
SET maintenance_work_mem = '2GB';
SET max_parallel_workers_per_gather = 12;

-- Fast exact topology creation (Bypass pgr_createTopology for perfect snaps)
DROP TABLE IF EXISTS edge_candidates_merged_vertices_pgr CASCADE;

CREATE UNLOGGED TABLE edge_candidates_merged_vertices_pgr (
    id BIGSERIAL PRIMARY KEY,
    the_geom GEOMETRY(Point, 4326)
);

INSERT INTO edge_candidates_merged_vertices_pgr (the_geom)
SELECT geom FROM (
    SELECT ST_StartPoint(geom) AS geom FROM edge_candidates_merged
    UNION
    SELECT ST_EndPoint(geom) AS geom FROM edge_candidates_merged
) as pts
GROUP BY geom;

CREATE INDEX edge_vertices_idx ON edge_candidates_merged_vertices_pgr USING GIST (the_geom);

ALTER TABLE edge_candidates_merged ADD COLUMN IF NOT EXISTS source BIGINT;
ALTER TABLE edge_candidates_merged ADD COLUMN IF NOT EXISTS target BIGINT;

WITH starts AS (
    SELECT e.id as edge_id, v.id as node_id 
    FROM edge_candidates_merged e 
    JOIN edge_candidates_merged_vertices_pgr v ON ST_StartPoint(e.geom) = v.the_geom
)
UPDATE edge_candidates_merged e
SET source = s.node_id
FROM starts s WHERE e.id = s.edge_id;

WITH ends AS (
    SELECT e.id as edge_id, v.id as node_id 
    FROM edge_candidates_merged e 
    JOIN edge_candidates_merged_vertices_pgr v ON ST_EndPoint(e.geom) = v.the_geom
)
UPDATE edge_candidates_merged e
SET target = s.node_id
FROM ends s WHERE e.id = s.edge_id;

ANALYZE edge_candidates_merged;
)";

constexpr std::string_view FILL_NODES_SQL = R"(
TRUNCATE graphs.nodes CASCADE;
INSERT INTO graphs.nodes (id, osm_node_id, geom)
SELECT id, id, the_geom FROM edge_candidates_merged_vertices_pgr;
)";

constexpr std::string_view FILL_EDGES_SQL = R"(
TRUNCATE graphs.edges CASCADE;
INSERT INTO graphs.edges (
    osm_way_id, source_id, target_id, geometry, 
    length_m, speed_limit_kmh, lanes, oneway, highway_type, 
    osm_tags, max_speed, effective_speed_kmh, duration, is_open, cost, reverse_cost
)
WITH calculated_speeds AS (
    SELECT 
        ec.id as osm_way_id,
        n.source, n.target, n.geom, 
        ST_Length(n.geom::geography) as len,
        CASE 
            WHEN ec.maxspeed ~ '^[0-9]+$' THEN ec.maxspeed::float
            WHEN ec.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link') THEN 110.0
            WHEN ec.highway IN ('primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link') THEN 60.0
            WHEN ec.highway IN ('residential', 'living_street', 'service', 'unclassified') THEN 20.0
            ELSE 60.0 
        END as spd_limit,
        COALESCE(ec.lanes, 1) as lanes, 
        ec.oneway, ec.highway, ec.tags,
        CASE 
            WHEN ec.maxspeed ~ '^[0-9]+$' THEN ec.maxspeed::float
            WHEN ec.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link') THEN 110.0
            WHEN ec.highway IN ('residential', 'living_street', 'service') THEN 20.0
            ELSE 60.0 
        END as max_spd
    FROM edge_candidates_merged n
    JOIN edge_candidates ec ON n.old_id = ec.id
    WHERE n.source IS NOT NULL AND n.target IS NOT NULL
)
SELECT 
    osm_way_id, source, target, geom, len, 
    spd_limit, lanes, oneway, highway, tags, max_spd,
    spd_limit, 
    len / GREATEST(spd_limit / 3.6, 0.1), 
    true,
    CASE WHEN oneway = -1 THEN -1.0 ELSE len / GREATEST(spd_limit / 3.6, 0.1) END,
    CASE WHEN oneway = 1 THEN -1.0 ELSE len / GREATEST(spd_limit / 3.6, 0.1) END
FROM calculated_speeds;
)";

constexpr std::string_view CLEANUP_SQL = R"(
ANALYZE graphs.nodes;
ANALYZE graphs.edges;
DROP TABLE IF EXISTS edge_candidates CASCADE;
DROP TABLE IF EXISTS edge_candidates_merged CASCADE;
DROP TABLE IF EXISTS edge_candidates_merged_vertices_pgr CASCADE;
)";

// ============================================================================
// STAGE 2: LCC ISOLATION
// ============================================================================
// Используется алгоритм Тарьяна (pgr_connectedComponents) для поиска кластеров
constexpr std::string_view ISOLATE_LCC_SQL = R"(
WITH components AS (
    SELECT component, node 
    FROM pgr_connectedComponents('SELECT id, source_id as source, target_id as target, cost, reverse_cost FROM graphs.edges')
),
component_sizes AS (
    SELECT component, count(*) as size FROM components GROUP BY component
),
largest_component AS (
    SELECT component FROM component_sizes ORDER BY size DESC LIMIT 1
),
valid_nodes AS (
    SELECT node FROM components WHERE component = (SELECT component FROM largest_component)
)
DELETE FROM graphs.nodes WHERE id NOT IN (SELECT node FROM valid_nodes);
-- Удаление nodes вызовет CASCADE DELETE для всех изолированных edges
ANALYZE graphs.nodes;
ANALYZE graphs.edges;
)";

} // namespace traffic::graph_builder
