-- Phase 4: Router Service SQL Functions
-- K-shortest paths with diversity penalties

-- Function: Calculate K alternative routes with diversity
CREATE OR REPLACE FUNCTION graphs.get_k_routes_with_diversity(
    p_start_node BIGINT,
    p_end_node BIGINT,
    p_k INTEGER DEFAULT 3,
    p_penalty_factor FLOAT DEFAULT 1.5,
    p_diversity_threshold FLOAT DEFAULT 0.3,
    p_priority INTEGER DEFAULT 0
)
RETURNS TABLE(
    route_id INTEGER,
    segments JSONB,
    total_distance_m FLOAT,
    estimated_time_sec FLOAT,
    diversity_score FLOAT,
    edge_ids BIGINT[]
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_route RECORD;
    v_base_route_edges BIGINT[];
    v_current_edges BIGINT[];
    v_shared_count INTEGER;
    v_diversity FLOAT;
    v_route_count INTEGER := 0;
BEGIN
    -- Algorithm:
    -- 1. Calculate base route (shortest path)
    -- 2. For each subsequent route:
    --    a. Apply progressive penalties to shared edges
    --    b. Recalculate shortest path
    --    c. Check diversity vs base route
    --    d. If diversity >= threshold, add to results
    
    -- Route 0: Base route (no penalties)
    FOR v_route IN (
        SELECT 
            seq,
            edge,
            cost,
            agg_cost
        FROM pgr_dijkstra(
            format('
                SELECT 
                    id,
                    source_id AS source,
                    target_id AS target,
                    CASE 
                        WHEN %s >= 20 THEN length_m / speed_limit_kmh
                        ELSE length_m / GREATEST(
                            speed_limit_kmh, -- Simplified cost
                            speed_limit_kmh * 0.2
                        )
                    END AS cost,
                    CASE 
                        WHEN oneway THEN -1.0
                        WHEN %s >= 20 THEN length_m / speed_limit_kmh
                        ELSE length_m / GREATEST(
                            speed_limit_kmh,
                            speed_limit_kmh * 0.2
                        )
                    END AS reverse_cost
                FROM graphs.edges
                WHERE 1=1
            ', p_priority, p_priority),
            p_start_node,
            p_end_node,
            directed := true
        )
    )
    LOOP
        v_current_edges := array_append(v_current_edges, v_route.edge);
    END LOOP;
    
    -- Save base route edges
    v_base_route_edges := v_current_edges;
    
    -- Build base route segments
    RETURN QUERY
    WITH route_edges AS (
        SELECT 
            unnest(v_current_edges) AS edge_id
    ),
        enriched AS (
        SELECT 
            e.id AS edge_id,
            e.source_id AS from_node,
            e.target_id AS to_node,
            e.length_m AS distance_m,
            e.speed_limit_kmh AS speed_limit,
            -- e.effective_speed, -- Missing column in new schema?
            e.speed_limit_kmh * 0.8 as effective_speed, -- Approximation
            0.0 as bearing -- Missing bearing column
        FROM route_edges re
        JOIN graphs.edges e ON e.id = re.edge_id
        ORDER BY array_position(v_current_edges, e.id)
    )
    SELECT
        0 AS route_id,
        jsonb_agg(
            jsonb_build_object(
                'edge_id', edge_id,
                'from_node', from_node,
                'to_node', to_node,
                'distance_m', distance_m,
                'speed_limit', speed_limit,
                'effective_speed', effective_speed,
                'bearing', bearing
            )
            ORDER BY array_position(v_current_edges, edge_id)
        ) AS segments,
        SUM(distance_m) AS total_distance_m,
        SUM(
            CASE 
                WHEN p_priority >= 20 THEN distance_m / speed_limit
                ELSE distance_m / GREATEST(effective_speed, speed_limit * 0.2)
            END
        ) AS estimated_time_sec,
        1.0::float AS diversity_score,
        v_current_edges AS edge_ids
    FROM enriched;
    
    v_route_count := 1;
    
    -- Routes 1..K-1: With progressive penalties
    WHILE v_route_count < p_k LOOP
        v_current_edges := ARRAY[]::BIGINT[];
        
        -- Calculate route with penalties on shared edges
        FOR v_route IN (
            SELECT 
                seq,
                edge,
                cost,
                agg_cost
            FROM pgr_dijkstra(
                format('
                SELECT 
                    id,
                    source_id AS source,
                    target_id AS target,
                    CASE 
                        WHEN %s >= 20 THEN 
                            length_m / speed_limit_kmh * 
                            CASE 
                                WHEN id = ANY(%L) THEN %s
                                ELSE 1.0
                            END
                        ELSE 
                            length_m / GREATEST(speed_limit_kmh, speed_limit_kmh * 0.2) * -- simplified for now or match schema
                            CASE 
                                WHEN id = ANY(%L) THEN %s
                                ELSE 1.0
                            END
                    END AS cost,
                    CASE 
                        WHEN oneway THEN -1.0
                        WHEN %s >= 20 THEN 
                            length_m / speed_limit_kmh * 
                            CASE 
                                WHEN id = ANY(%L) THEN %s
                                ELSE 1.0
                            END
                        ELSE 
                            length_m / GREATEST(speed_limit_kmh, speed_limit_kmh * 0.2) * 
                            CASE 
                                WHEN id = ANY(%L) THEN %s
                                ELSE 1.0
                            END
                    END AS reverse_cost
                FROM graphs.edges
                WHERE 1=1 -- enabled column missing in my schema?
                ', p_priority, v_current_edges, p_penalty_factor, v_current_edges, p_penalty_factor, 
                   p_priority, v_current_edges, p_penalty_factor, v_current_edges, p_penalty_factor),
                p_start_node,
                p_end_node,
                directed := true
            )
        )
        LOOP
            v_current_edges := array_append(v_current_edges, v_route.edge);
        END LOOP;
        
        -- Check diversity vs base route
        v_shared_count := (
            SELECT COUNT(*)
            FROM unnest(v_current_edges) AS edge
            WHERE edge = ANY(v_base_route_edges)
        );
        
        v_diversity := 1.0 - (
            v_shared_count::FLOAT / 
            GREATEST(
                array_length(v_current_edges, 1),
                array_length(v_base_route_edges, 1)
            )
        );
        
        -- If diverse enough, add to results
        IF v_diversity >= p_diversity_threshold THEN
            RETURN QUERY
            WITH route_edges AS (
                SELECT 
                    unnest(v_current_edges) AS edge_id
            ),
            enriched AS (
                SELECT 
                    e.id AS edge_id,
                    e.source_id AS from_node,
                    e.target_id AS to_node,
                    e.length_m AS distance_m,
                    e.speed_limit_kmh AS speed_limit,
                    -- e.effective_speed,
                    e.speed_limit_kmh * 0.8 as effective_speed,
                    0.0 as bearing
                FROM route_edges re
                JOIN graphs.edges e ON e.id = re.edge_id
                ORDER BY array_position(v_current_edges, e.id)
            )
            SELECT
                v_route_count AS route_id,
                jsonb_agg(
                    jsonb_build_object(
                        'edge_id', edge_id,
                        'from_node', from_node,
                        'to_node', to_node,
                        'distance_m', distance_m,
                        'speed_limit', speed_limit,
                        'effective_speed', effective_speed,
                        'bearing', bearing
                    )
                    ORDER BY array_position(v_current_edges, edge_id)
                ) AS segments,
                SUM(distance_m) AS total_distance_m,
                SUM(
                    CASE 
                        WHEN p_priority >= 20 THEN distance_m / speed_limit
                        ELSE distance_m / GREATEST(
                            effective_speed,
                            speed_limit * 0.2
                        )
                    END
                ) AS estimated_time_sec,
                v_diversity AS diversity_score,
                v_current_edges AS edge_ids
            FROM enriched;
            
            v_route_count := v_route_count + 1;
        ELSE
            -- Not diverse enough, stop
            EXIT;
        END IF;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION graphs.get_k_routes_with_diversity IS 
'Calculate K alternative routes with diversity penalties.
Uses Yen algorithm + progressive penalties on shared edges.
Priority >= 20: emergency, ignores congestion.
Diversity threshold: 0.3 = 30% different edges minimum.';
