#pragma once

#include <string_view>

// ============================================================================
// NAV MAS — SQL СХЕМА ДЛЯ GRAPH BUILDER
//
// Порядок этапов:
//   1. ExtractCandidates  → edge_candidates (из OSM, с фильтрами доступа/барьеров)
//   2. GridNoding         → edge_candidates_merged (нодирование по тайлам, ST_SnapToGrid)
//   3. CreateTopology     → source/target к merged + graphs.nodes
//   4. PopulateAttributes → graphs.edges с атрибутами
//   5. IsolateLCC         → удаление изолированных (с FK CASCADE)
//   6. BuildEdgeBasedGraph → graphs.eb_nodes (направленные сегменты) +
//                            graphs.eb_edges (разрешённые маневры, с TR)
//   7-10. Дампы: csr / csr_rev / attributes / r-tree
// ============================================================================

namespace traffic::graph_builder
{

// ============================================================================
// ИНИЦИАЛИЗАЦИЯ СХЕМЫ
// ============================================================================
constexpr std::string_view DROP_SCHEMA_SQL = R"(
DROP SCHEMA IF EXISTS graphs CASCADE;
)";

constexpr std::string_view INIT_SCHEMA_SQL = R"(
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

CREATE SCHEMA IF NOT EXISTS graphs;

-- Таблица состояния пайплайна (чекпоинты)
CREATE TABLE IF NOT EXISTS graphs.builder_state (
    stage        VARCHAR(64) PRIMARY KEY,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Перекрёстки (узлы дорожной сети, Node-based слой)
CREATE TABLE IF NOT EXISTS graphs.nodes (
    id          BIGSERIAL PRIMARY KEY,
    osm_node_id BIGINT UNIQUE NOT NULL,
    geom        GEOMETRY(POINT, 4326) NOT NULL
);

-- Рёбра рабочего Node-based графа (промежуточный слой)
-- FOREIGN KEY с ON DELETE CASCADE: удаление узла → автоматически удаляет связанные рёбра
CREATE TABLE graphs.edges (
    id               BIGSERIAL PRIMARY KEY,
    source_id        BIGINT REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    target_id        BIGINT REFERENCES graphs.nodes(id) ON DELETE CASCADE,
    osm_way_id       BIGINT,
    geometry         GEOMETRY(LineString, 4326),
    length_m         FLOAT,
    speed_limit_kmh  FLOAT,
    lanes            INT,
    oneway           INT,
    highway_type     TEXT,
    osm_tags         JSONB,
    max_speed        FLOAT,
    duration         FLOAT,
    is_open          BOOLEAN  DEFAULT TRUE,
    current_load     INT      DEFAULT 0,
    effective_speed_kmh FLOAT DEFAULT 60.0,
    cost             FLOAT,
    reverse_cost     FLOAT
);
CREATE INDEX idx_graphs_edges_source ON graphs.edges(source_id);
CREATE INDEX idx_graphs_edges_target ON graphs.edges(target_id);
CREATE INDEX idx_graphs_edges_geom   ON graphs.edges USING GIST(geometry);
)";

// ============================================================================
// STAGE 1: ИЗВЛЕЧЕНИЕ КАНДИДАТОВ (с фильтрами доступа и барьеров)
// ============================================================================
constexpr std::string_view INIT_CANDIDATES_SQL = R"(
DROP TABLE IF EXISTS edge_candidates CASCADE;
CREATE TABLE edge_candidates (
    id       BIGINT,
    tags     JSONB,
    highway  TEXT,
    maxspeed TEXT,
    lanes    INT,
    oneway   INT,
    source   INT,
    target   INT,
    geom     GEOMETRY(LineString, 4326),
    is_ground BOOLEAN
);
)";

// Batch-вставка кандидатов из osm.ways.
// Фильтры:
//   1. Только дороги общего пользования (highway IN (...))
//   2. Исключаем перекрытые для доступа (access=private/no/customers)
//   3. Исключаем физические барьеры (barrier=gate/fence/wall/bollard)
//   4. ST_SnapToGrid(0.000001 ≈ ~10 см) — гарантированное совпадение
//      вершин на границах тайлов после Grid Noding
constexpr std::string_view INSERT_CANDIDATES_BATCH_SQL = R"(
INSERT INTO edge_candidates (id, tags, highway, maxspeed, lanes, oneway, geom, is_ground)
SELECT
    id,
    tags,
    tags->>'highway'  AS highway,
    tags->>'maxspeed' AS maxspeed,
    (tags->>'lanes')::int AS lanes,
    CASE
        WHEN tags->>'oneway' = 'yes'  THEN  1
        WHEN tags->>'oneway' = '-1'   THEN -1
        ELSE 0
    END AS oneway,
    -- ST_SnapToGrid предотвращает микро-зазоры. Убираем ST_Subdivide для сохранения целостности путей.
    ST_SnapToGrid(
        ST_Segmentize(geom::geography, 50)::geometry,
        0.00001
    ) AS geom,
    CASE
        WHEN tags->>'bridge'  IS NOT NULL                    THEN FALSE
        WHEN tags->>'tunnel'  IS NOT NULL                    THEN FALSE
        WHEN tags->>'layer'   IS NOT NULL
             AND tags->>'layer' != '0'                       THEN FALSE
        ELSE TRUE
    END AS is_ground
FROM osm.ways
WHERE
    tags ? 'highway'
    AND tags->>'highway' IN (
        'motorway', 'motorway_link', 'trunk', 'trunk_link',
        'primary', 'primary_link', 'secondary', 'secondary_link',
        'tertiary', 'tertiary_link', 'residential', 'living_street',
        'service', 'unclassified'
    )
    -- Фильтр доступа: исключаем недоступные для общего движения
    AND (
        tags->>'access' IS NULL
        OR tags->>'access' NOT IN ('private', 'no', 'customers', 'delivery')
    )
    -- Фильтр барьеров: исключаем физически непроходимые объекты
    AND (
        tags->>'barrier' IS NULL
        OR tags->>'barrier' NOT IN ('gate', 'fence', 'wall', 'bollard', 'block')
    )
ORDER BY id
LIMIT {} OFFSET {};
)";

constexpr std::string_view INDEX_CANDIDATES_SQL = R"(
CREATE INDEX idx_ec_geom     ON edge_candidates USING GIST(geom);
CREATE INDEX idx_ec_id       ON edge_candidates(id);
CREATE INDEX idx_ec_ground   ON edge_candidates(is_ground);
ANALYZE edge_candidates;
)";

// ============================================================================
// STAGE 2: GRID NODING (ST_SnapToGrid — фикс фрагментации тайлов)
// ============================================================================
constexpr std::string_view INIT_MERGED_SQL = R"(
DROP TABLE IF EXISTS edge_candidates_merged CASCADE;
CREATE TABLE edge_candidates_merged (
    id     SERIAL PRIMARY KEY,
    old_id BIGINT,
    sub_id INT    DEFAULT 1,
    source INT,
    target INT,
    geom   GEOMETRY(LineString, 4326)
);
CREATE INDEX idx_ecm_geom ON edge_candidates_merged USING GIST(geom);
)";

// Нодирует геометрии в пределах тайла. Для устранения фрагментации:
// 1. Расширяем bbox тайла на overlap (0.001°) — перекрытие соседних тайлов
// 2. ST_SnapToGrid(0.000001) применяется к узлам — вершины на границах
//    тайлов получают одинаковые флоат-координаты → pgr_createTopology
//    соединяет их в единую сеть
constexpr std::string_view GRID_NODING_TILE_SQL = R"(
WITH
selection AS (
    SELECT id, geom FROM edge_candidates
    WHERE is_ground = TRUE
      AND geom && ST_Expand(ST_MakeEnvelope({0}, {1}, {2}, {3}, 4326), 0.001)
),
noded_geoms AS (
    SELECT (ST_Dump(ST_Node(ST_Collect(geom)))).geom AS geom
    FROM selection
),
-- ST_SnapToGrid финализирует точность - вершины двух соседних тайлов,
-- которые были "почти одинаковыми", становятся математически идентичными
snapped AS (
    SELECT ST_SnapToGrid(geom, 0.00001) AS geom FROM noded_geoms
    WHERE ST_Contains(ST_MakeEnvelope({0}, {1}, {2}, {3}, 4326), ST_Centroid(geom))
)
INSERT INTO edge_candidates_merged (old_id, geom)
SELECT DISTINCT ON (s.geom)
    e.id,
    s.geom
FROM snapped s
JOIN selection e ON ST_Intersects(s.geom, e.geom)
               AND ST_Length(ST_Intersection(s.geom, e.geom)) > 0.9 * ST_Length(s.geom);
)";

constexpr std::string_view COPY_BRIDGES_SQL = R"(
INSERT INTO edge_candidates_merged (old_id, geom)
SELECT id, ST_SnapToGrid(geom, 0.00001) FROM edge_candidates WHERE is_ground = FALSE;
)";

constexpr std::string_view INDEX_MERGED_SQL = R"(
CREATE INDEX IF NOT EXISTS idx_ecm_old_id ON edge_candidates_merged(old_id);
ANALYZE edge_candidates_merged;
)";

// ============================================================================
// STAGE 3: ТОПОЛОГИЯ (Hash Join вместо pgr_createTopology)
// ============================================================================
constexpr std::string_view CREATE_TOPOLOGY_SQL = R"(
SET maintenance_work_mem = '2GB';
SET max_parallel_workers_per_gather = 12;

DROP TABLE IF EXISTS edge_candidates_merged_vertices_pgr CASCADE;

CREATE UNLOGGED TABLE edge_candidates_merged_vertices_pgr (
    id       BIGSERIAL PRIMARY KEY,
    the_geom GEOMETRY(Point, 4326)
);

-- Уникальные вершины (start + end points) всех нодированных рёбер
-- Используем ST_SnapToGrid(0.00001) для группировки, чтобы "склеить" микро-зазоры
INSERT INTO edge_candidates_merged_vertices_pgr (the_geom)
SELECT ST_SnapToGrid(geom, 0.00001) FROM (
    SELECT ST_StartPoint(geom) AS geom FROM edge_candidates_merged
    UNION
    SELECT ST_EndPoint(geom)   AS geom FROM edge_candidates_merged
) AS pts
GROUP BY ST_SnapToGrid(geom, 0.00001);

CREATE INDEX edge_vertices_idx ON edge_candidates_merged_vertices_pgr USING GIST(the_geom);

ALTER TABLE edge_candidates_merged ADD COLUMN IF NOT EXISTS source BIGINT;
ALTER TABLE edge_candidates_merged ADD COLUMN IF NOT EXISTS target BIGINT;

WITH starts AS (
    SELECT e.id AS edge_id, v.id AS node_id
    FROM edge_candidates_merged e
    JOIN edge_candidates_merged_vertices_pgr v
      ON ST_DWithin(ST_StartPoint(e.geom), v.the_geom, 0.00001)
)
UPDATE edge_candidates_merged e
SET source = s.node_id
FROM starts s WHERE e.id = s.edge_id;

-- target
WITH ends AS (
    SELECT e.id AS edge_id, v.id AS node_id
    FROM edge_candidates_merged e
    JOIN edge_candidates_merged_vertices_pgr v
      ON ST_DWithin(ST_EndPoint(e.geom), v.the_geom, 0.00001)
)
UPDATE edge_candidates_merged e
SET target = s.node_id
FROM ends   s WHERE e.id = s.edge_id;

ANALYZE edge_candidates_merged;
)";

constexpr std::string_view FILL_NODES_SQL = R"(
TRUNCATE graphs.nodes CASCADE;
INSERT INTO graphs.nodes (id, osm_node_id, geom)
SELECT id, id, the_geom FROM edge_candidates_merged_vertices_pgr;
)";

// ============================================================================
// STAGE 4: АТРИБУТЫ (заполнение graphs.edges)
// ============================================================================
constexpr std::string_view FILL_EDGES_SQL = R"(
TRUNCATE graphs.edges CASCADE;
INSERT INTO graphs.edges (
    osm_way_id, source_id, target_id, geometry,
    length_m, speed_limit_kmh, lanes, oneway, highway_type,
    osm_tags, max_speed, effective_speed_kmh, duration, is_open, cost, reverse_cost
)
WITH calculated AS (
    SELECT
        ec.id                             AS osm_way_id,
        n.source, n.target, n.geom,
        ST_Length(n.geom::geography)      AS len,
        CASE
            WHEN ec.maxspeed ~ '^[0-9]+$' THEN ec.maxspeed::FLOAT
            WHEN ec.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')               THEN 110.0
            WHEN ec.highway IN ('primary', 'primary_link', 'secondary', 'secondary_link')         THEN  60.0
            WHEN ec.highway IN ('tertiary', 'tertiary_link')                                       THEN  50.0
            WHEN ec.highway IN ('residential', 'living_street', 'service', 'unclassified')        THEN  20.0
            ELSE 30.0
        END                               AS spd_limit,
        COALESCE(ec.lanes, 1)             AS lanes,
        ec.oneway, ec.highway, ec.tags
    FROM edge_candidates_merged n
    JOIN edge_candidates ec ON n.old_id = ec.id
    WHERE n.source IS NOT NULL AND n.target IS NOT NULL
),
-- t_free вычисляется с добавкой SPEED_TOLERANCE (+19 км/ч)
with_time AS (
    SELECT *,
        spd_limit + 19.0                               AS eff_speed,
        len / GREATEST((spd_limit + 19.0) / 3.6, 0.1) AS t_free
    FROM calculated
)
SELECT
    osm_way_id, source, target, geom, len,
    spd_limit, lanes, oneway, highway, tags,
    spd_limit,   -- max_speed (официальный лимит)
    eff_speed,   -- effective_speed_kmh (с учётом +19)
    t_free,      -- duration = t_free
    TRUE,
    -- cost=-1 означает "запрещено", pgr-конвенция
    CASE WHEN oneway = -1 THEN -1.0 ELSE t_free END,
    CASE WHEN oneway =  1 THEN -1.0 ELSE t_free END
FROM with_time;
)";

constexpr std::string_view CLEANUP_SQL = R"(
ANALYZE graphs.nodes;
ANALYZE graphs.edges;
DROP TABLE IF EXISTS edge_candidates CASCADE;
DROP TABLE IF EXISTS edge_candidates_merged CASCADE;
DROP TABLE IF EXISTS edge_candidates_merged_vertices_pgr CASCADE;
)";

// ============================================================================
// STAGE 5: LCC — ЛОГИРОВАНИЕ И ИЗОЛЯЦИЯ (алгоритм Тарьяна через pgr)
// ============================================================================

// Выполняется ПЕРЕД удалением. Выводим Top-5 компонент.
// Результат идёт через C++ код и печатается в stdout.
constexpr std::string_view LOG_LCC_DISTRIBUTION_SQL = R"(
SELECT
    component,
    COUNT(*) AS node_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_total
FROM pgr_connectedComponents(
    'SELECT id, source_id AS source, target_id AS target, cost, reverse_cost
     FROM graphs.edges
     WHERE cost != -1 OR reverse_cost != -1'
)
GROUP BY component
ORDER BY node_count DESC
LIMIT 5;
)";

// Используется алгоритм Тарьяна (pgr_connectedComponents) для поиска кластеров.
// В graphs.edges есть FK (source_id, target_id) → graphs.nodes ON DELETE CASCADE,
// поэтому удаление узла автоматически удаляет все связанные рёбра.
constexpr std::string_view ISOLATE_LCC_SQL = R"(
WITH components AS (
    SELECT component, node
    FROM pgr_connectedComponents(
        'SELECT id, source_id AS source, target_id AS target, cost, reverse_cost
         FROM graphs.edges
         WHERE cost != -1 OR reverse_cost != -1'
    )
),
component_sizes AS (
    SELECT component, COUNT(*) AS size FROM components GROUP BY component
),
largest AS (
    SELECT component FROM component_sizes ORDER BY size DESC LIMIT 1
),
valid_nodes AS (
    SELECT node FROM components WHERE component = (SELECT component FROM largest)
)
DELETE FROM graphs.nodes WHERE id NOT IN (SELECT node FROM valid_nodes);

ANALYZE graphs.nodes;
ANALYZE graphs.edges;
)";

// ============================================================================
// STAGE 6: EDGE-BASED ГРАФ (Line Graph трансформация)
// ============================================================================

// eb_nodes — направленные сегменты (= узлы Edge-based графа)
// Для двусторонней дороги создаётся 2 строки (forward + backward).
// Для односторонней — 1 строка.
//
// Схема: eb_nodes.id = плоский dense индекс (0..N-1), присваивается
// при DumpCSR через ROW_NUMBER() / сериал.

constexpr std::string_view INIT_EB_GRAPH_SQL = R"(
DROP TABLE IF EXISTS graphs.eb_edges CASCADE;
DROP TABLE IF EXISTS graphs.eb_nodes CASCADE;

-- Направленные сегменты (узлы Line-Graph)
CREATE TABLE graphs.eb_nodes (
    id          BIGSERIAL PRIMARY KEY,
    orig_edge_id BIGINT  NOT NULL,          -- FK → graphs.edges.id (исходное ребро)
    entry_node  BIGINT  NOT NULL,           -- откуда въезжаем (перекрёсток)
    exit_node   BIGINT  NOT NULL,           -- куда выезжаем (следующий перекрёсток)
    geom        GEOMETRY(LineString, 4326), -- геометрия сегмента (или ST_Reverse для обр. направления)
    length_m    FLOAT   NOT NULL,
    t_free      FLOAT   NOT NULL,           -- free-flow время (с учётом +19 км/ч)
    speed_kmh   FLOAT   NOT NULL,
    lanes       INT     DEFAULT 1,
    highway     TEXT,
    oneway      INT     DEFAULT 0
);
CREATE INDEX idx_eb_nodes_exit  ON graphs.eb_nodes(exit_node);
CREATE INDEX idx_eb_nodes_entry ON graphs.eb_nodes(entry_node);
CREATE INDEX idx_eb_nodes_geom  ON graphs.eb_nodes USING GIST(geom);

-- Маневры (рёбра Line-Graph)
CREATE TABLE graphs.eb_edges (
    id            BIGSERIAL PRIMARY KEY,
    from_eb_node  BIGINT  NOT NULL REFERENCES graphs.eb_nodes(id) ON DELETE CASCADE,
    to_eb_node    BIGINT  NOT NULL REFERENCES graphs.eb_nodes(id) ON DELETE CASCADE,
    junction_node BIGINT  NOT NULL,             -- перекрёсток где происходит маневр
    turn_type     SMALLINT NOT NULL DEFAULT 0,  -- 0=straight,1=right,2=left,3=uturn
    maneuver_time FLOAT   NOT NULL DEFAULT 0    -- штраф за маневр (сек)
);
CREATE INDEX idx_eb_edges_from ON graphs.eb_edges(from_eb_node);
)";

// Заполняет eb_nodes из graphs.edges.
// Для каждого двустороннего ребра → 2 направленные записи.
// Для одностороннего → 1 запись.
// t_free уже посчитан в graphs.edges.duration (= len / (spd+19)/3.6).
constexpr std::string_view FILL_EB_NODES_SQL = R"(
-- Прямое направление: cost > 0 (можно ехать source→target)
INSERT INTO graphs.eb_nodes
    (orig_edge_id, entry_node, exit_node, geom, length_m, t_free, speed_kmh, lanes, highway, oneway)
SELECT
    id, source_id, target_id,
    geometry, length_m, duration,
    effective_speed_kmh, COALESCE(lanes, 1), highway_type, oneway
FROM graphs.edges
WHERE cost > 0 AND source_id IS NOT NULL AND target_id IS NOT NULL;

-- Обратное направление: reverse_cost > 0 AND не oneway=1
INSERT INTO graphs.eb_nodes
    (orig_edge_id, entry_node, exit_node, geom, length_m, t_free, speed_kmh, lanes, highway, oneway)
SELECT
    id, target_id, source_id,
    ST_Reverse(geometry), length_m, duration,
    effective_speed_kmh, COALESCE(lanes, 1), highway_type, oneway
FROM graphs.edges
WHERE reverse_cost > 0 AND source_id IS NOT NULL AND target_id IS NOT NULL;

ANALYZE graphs.eb_nodes;
)";

// Маневры — соединяем eb_nodes через общий перекрёсток:
//   from_node.exit_node = to_node.entry_node = перекрёсток
//
// Тип маневра (turn_type) вычисляется через угол между геометриями:
//   - bearing от конца from → bearing из начала to
//   - angle diff: right = (0°..100°], left = (-100°..0°], uturn = (>160° | <-160°)
//
// Запреты поворотов (TR) из osm.relations:
//   Отношение с type=restriction содержит members-массив:
//     [{"type":"W","ref":<way_id>,"role":"from"},
//      {"type":"N","ref":<node_id>,"role":"via"},
//      {"type":"W","ref":<way_id>,"role":"to"}]
//   Для "no_*" ограничений удаляем пары (from_way, via_node, to_way).
//   Для "only_*" ограничений удаляем ВСЕ пары кроме разрешённой.
constexpr std::string_view FILL_EB_EDGES_SQL = R"(
-- ======================================================================
-- Шаг 1: Построить все потенциальные маневры (пары eb_nodes через junction)
-- ======================================================================
WITH raw_maneuvers AS (
    SELECT
        f.id   AS from_eb,
        t.id   AS to_eb,
        f.exit_node AS junction,
        -- Угол поворота: разница азимутов (конец from → начало to)
        -- ST_Azimuth возвращает угол в радианах, конвертируем в градусы
        DEGREES(
            ST_Azimuth(
                ST_EndPoint(f.geom),
                ST_StartPoint(t.geom)
            )
            -
            ST_Azimuth(
                ST_PointN(f.geom, GREATEST(ST_NPoints(f.geom) - 1, 1)),
                ST_EndPoint(f.geom)
            )
        ) AS raw_angle,
        f.orig_edge_id AS from_way_id,
        t.orig_edge_id AS to_way_id,
        t.highway      AS to_highway
    FROM graphs.eb_nodes f
    JOIN graphs.eb_nodes t ON f.exit_node = t.entry_node
    -- Не разрешаем U-turn если это магистраль
    WHERE NOT (
        f.orig_edge_id = t.orig_edge_id
        AND t.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')
    )
),
-- Нормализуем угол в диапазон (-180, 180]
normalized AS (
    SELECT *,
        CASE
            WHEN raw_angle > 180  THEN raw_angle - 360
            WHEN raw_angle <= -180 THEN raw_angle + 360
            ELSE raw_angle
        END AS angle
    FROM raw_maneuvers
),
-- Классифицируем тип поворота
classified AS (
    SELECT *,
        CASE
            WHEN from_way_id = to_way_id AND ABS(angle) > 150
                THEN 3  -- разворот (U-turn)
            WHEN angle >   20 THEN 1   -- правый поворот
            WHEN angle <  -20 THEN 2   -- левый поворот
            ELSE 0                     -- прямо
        END AS turn_type
    FROM normalized
),

-- ======================================================================
-- Шаг 2: Запреты поворотов из osm.relations
-- Формат members (jsonb array): [{"type":"W","ref":way_id,"role":"from"}, ...]
-- ======================================================================
restrictions AS (
    SELECT
        (elem->>'ref')::BIGINT AS way_id,
        role,
        r.id            AS rel_id,
        r.tags->>'restriction' AS restriction_type,
        -- Извлекаем via-узел
        (SELECT (m->>'ref')::BIGINT
         FROM jsonb_array_elements(r.members) AS m
         WHERE m->>'role' = 'via' AND m->>'type' = 'N'
         LIMIT 1)       AS via_node
    FROM (SELECT 1) dummy
    LEFT JOIN osm.relations r ON (to_regclass('osm.relations') IS NOT NULL)
    CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN r.members IS NULL THEN '[]'::jsonb ELSE r.members END) WITH ORDINALITY AS arr(elem, ord)
    WHERE r.tags->>'type' = 'restriction'
      AND r.members IS NOT NULL
      AND (elem->>'role' = 'from' OR elem->>'role' = 'to')
),
-- Собираем тройки (from_way, via_node, to_way, restriction_type)
tr_pairs AS (
    SELECT
        f.way_id   AS from_way,
        f.via_node AS via_node,
        t.way_id   AS to_way,
        f.restriction_type
    FROM restrictions f
    JOIN restrictions t
      ON f.rel_id = t.rel_id
     AND f.role = 'from'
     AND t.role = 'to'
    WHERE f.via_node IS NOT NULL
),

-- ======================================================================
-- Шаг 3: Фильтрация по запретам
-- ======================================================================

-- "no_*" запрещённые пары: удаляем прямо
forbidden AS (
    SELECT from_way, via_node, to_way
    FROM tr_pairs
    WHERE restriction_type LIKE 'no_%'
),

-- "only_*" принудительные: для каждой "from" пары разрешён ТОЛЬКО один "to"
-- Все остальные to_way из того же (from_way, via_node) — запрещены
allowed_only AS (
    SELECT from_way, via_node, to_way
    FROM tr_pairs
    WHERE restriction_type LIKE 'only_%'
),

-- Для "only_*" блокируем все маневры кроме разрешённого
only_forbidden AS (
    SELECT c.from_eb, c.to_eb
    FROM classified c
    JOIN allowed_only ao
      ON c.from_way_id = ao.from_way AND c.junction = ao.via_node
     AND c.to_way_id  != ao.to_way   -- всё, кроме разрешённого, запрещено
),

legal_maneuvers AS (
    SELECT c.*
    FROM classified c
    -- Исключаем прямые запреты (no_*)
    WHERE NOT EXISTS (
        SELECT 1 FROM forbidden f
        WHERE f.from_way = c.from_way_id
          AND f.via_node  = c.junction
          AND f.to_way    = c.to_way_id
    )
    -- Исключаем нарушения only_*
    AND NOT EXISTS (
        SELECT 1 FROM only_forbidden of2
        WHERE of2.from_eb = c.from_eb AND of2.to_eb = c.to_eb
    )
)

-- ======================================================================
-- Шаг 4: Вставляем легальные маневры в eb_edges
-- Штраф за маневр — из road_config.hpp константы, но здесь SQL:
--   right=1s, straight=0s, left=4s, uturn=20s (fallback)
-- Точные значения из road_config.hpp применяются при DumpCSR (C++ слой).
-- ======================================================================
INSERT INTO graphs.eb_edges
    (from_eb_node, to_eb_node, junction_node, turn_type, maneuver_time)
SELECT
    from_eb, to_eb, junction,
    turn_type,
    CASE turn_type
        WHEN 0 THEN 0.0    -- прямо: без штрафа
        WHEN 1 THEN 1.0    -- право: минимальный штраф
        WHEN 2 THEN 4.0    -- лево: штраф за пересечение встречки
        WHEN 3 THEN 20.0   -- разворот
        ELSE 0.0
    END AS maneuver_time
FROM legal_maneuvers;

ANALYZE graphs.eb_edges;
)";

constexpr std::string_view FILL_EB_EDGES_NO_TR_SQL = R"(
-- Версия без TR (Turn Restrictions) для случаев, когда osm.relations отсутствует
WITH raw_maneuvers AS (
    SELECT
        f.id   AS from_eb,
        t.id   AS to_eb,
        f.exit_node AS junction,
        DEGREES(
            ST_Azimuth(ST_EndPoint(f.geom), ST_StartPoint(t.geom)) -
            ST_Azimuth(ST_PointN(f.geom, GREATEST(ST_NPoints(f.geom)-1, 1)), ST_EndPoint(f.geom))
        ) AS raw_angle,
        f.orig_edge_id AS from_way_id,
        t.orig_edge_id AS to_way_id,
        t.highway      AS to_highway
    FROM graphs.eb_nodes f
    JOIN graphs.eb_nodes t ON f.exit_node = t.entry_node
    WHERE NOT (
        f.orig_edge_id = t.orig_edge_id
        AND t.highway IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')
    )
),
normalized AS (
    SELECT *,
        CASE
            WHEN raw_angle > 180  THEN raw_angle - 360
            WHEN raw_angle <= -180 THEN raw_angle + 360
            ELSE raw_angle
        END AS angle
    FROM raw_maneuvers
),
classified AS (
    SELECT *,
        CASE
            WHEN from_way_id = to_way_id AND ABS(angle) > 150
                THEN 3  -- разворот
            WHEN angle >   20 THEN 1   -- правый
            WHEN angle <  -20 THEN 2   -- левый
            ELSE 0                     -- прямо
        END AS turn_type
    FROM normalized
)
INSERT INTO graphs.eb_edges
    (from_eb_node, to_eb_node, junction_node, turn_type, maneuver_time)
SELECT
    from_eb, to_eb, junction,
    turn_type,
    CASE turn_type
        WHEN 0 THEN 0.0
        WHEN 1 THEN 1.0
        WHEN 2 THEN 4.0
        WHEN 3 THEN 20.0
        ELSE 0.0
    END
FROM classified;

ANALYZE graphs.eb_edges;
)";

} // namespace traffic::graph_builder
