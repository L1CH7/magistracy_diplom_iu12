-- Migration 007: Create helper views for routing
-- Date: 2025-11-28
-- Purpose: Views for congestion analysis, adjacency lists, statistics

-- ==================== View 1: Edges with congestion ratio ==========
CREATE OR REPLACE VIEW graphs.edges_with_congestion AS
SELECT 
    e.*,
    CASE 
        WHEN e.capacity > 0 
        THEN e.current_load::FLOAT / e.capacity
        ELSE 0.0 
    END as congestion_ratio
FROM graphs.edges e;

COMMENT ON VIEW graphs.edges_with_congestion IS 'Edges with congestion_ratio = current_load / capacity';

-- ==================== View 2: Adjacency list ==========
CREATE OR REPLACE VIEW graphs.adjacency_list AS
SELECT 
    source as node_id,
    array_agg(id) as outgoing_edge_ids
FROM graphs.edges
GROUP BY source;

COMMENT ON VIEW graphs.adjacency_list IS 'Adjacency list: node_id → array of outgoing edge IDs';

-- ==================== View 3: Intersection analysis ==========
CREATE OR REPLACE VIEW graphs.intersection_analysis AS
SELECT 
    n.id,
    n.osm_node_id,
    COUNT(e.id) as degree,
    array_agg(DISTINCT e.highway) as highway_types,
    array_agg(DISTINCT e.access_type) as access_types
FROM graphs.nodes n
LEFT JOIN graphs.edges e ON n.id = e.source OR n.id = e.target
WHERE n.is_intersection = true
GROUP BY n.id, n.osm_node_id;

COMMENT ON VIEW graphs.intersection_analysis IS 'Intersection statistics: degree, highway types, access types';

-- ==================== View 4: Turn restriction summary ==========
CREATE OR REPLACE VIEW graphs.turn_restriction_summary AS
SELECT 
    v.id as via_node_id,
    v.osm_node_id,
    tr.restriction_type,
    COUNT(*) as count
FROM graphs.turn_restrictions tr
LEFT JOIN graphs.nodes v ON tr.via_node = v.id
GROUP BY v.id, v.osm_node_id, tr.restriction_type;

COMMENT ON VIEW graphs.turn_restriction_summary IS 'Turn restriction summary by node';
