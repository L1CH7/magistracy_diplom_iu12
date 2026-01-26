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
    v_all_penalized_edges BIGINT[] := ARRAY[]::BIGINT[];
    v_shared_count INTEGER;
    v_diversity FLOAT;
    v_route_count INTEGER := 0;
BEGIN
    -- Initialize cumulative penalty list with an empty array.
    -- v_all_penalized_edges will hold all edges from all discovered routes
    -- to penalize their reuse in future searches.

    WHILE v_route_count < p_k LOOP
        v_current_edges := ARRAY[]::BIGINT[];
        
        -- Temporary table to hold path structure for the current search
        CREATE TEMP TABLE IF NOT EXISTS current_path (
            seq INTEGER,
            node_id BIGINT,
            edge_id BIGINT,
            cost FLOAT
        ) ON COMMIT DROP;
        DELETE FROM current_path;

        -- Search for the shortest path given current penalties
        INSERT INTO current_path (seq, node_id, edge_id, cost)
        SELECT seq, node, edge, cost
        FROM pgr_dijkstra(
            format('
                SELECT 
                    id,
                    source_id AS source,
                    target_id AS target,
                    CASE 
                        WHEN %s >= 20 THEN 
                            length_m / GREATEST(speed_limit_kmh, 1.0) * 
                            CASE WHEN id = ANY(%L) THEN %s ELSE 1.0 END
                        ELSE 
                            length_m / GREATEST(speed_limit_kmh, 1.0) * 
                            CASE WHEN id = ANY(%L) THEN %s ELSE 1.0 END
                    END AS cost,
                    CASE 
                        WHEN oneway THEN -1.0
                        WHEN %s >= 20 THEN 
                            length_m / GREATEST(speed_limit_kmh, 1.0) * 
                            CASE WHEN id = ANY(%L) THEN %s ELSE 1.0 END
                        ELSE 
                            length_m / GREATEST(speed_limit_kmh, 1.0) * 
                            CASE WHEN id = ANY(%L) THEN %s ELSE 1.0 END
                    END AS reverse_cost
                FROM graphs.edges
                WHERE 1=1
            ', p_priority, v_all_penalized_edges, p_penalty_factor, v_all_penalized_edges, p_penalty_factor,
               p_priority, v_all_penalized_edges, p_penalty_factor, v_all_penalized_edges, p_penalty_factor),
            p_start_node,
            p_end_node,
            directed := true
        );

        -- Extract edge IDs for diversity check
        v_current_edges := (SELECT array_agg(edge_id ORDER BY seq) FROM current_path WHERE edge_id > 0);

        IF v_current_edges IS NULL OR array_length(v_current_edges, 1) = 0 THEN
            EXIT; -- No more routes possible
        END IF;

        -- Diversity check
        IF v_route_count = 0 THEN
            v_base_route_edges := v_current_edges;
            v_diversity := 1.0;
        ELSE
            v_shared_count := (
                SELECT COUNT(*)
                FROM unnest(v_current_edges) AS e
                WHERE e = ANY(v_base_route_edges)
            );
            v_diversity := 1.0 - (v_shared_count::FLOAT / GREATEST(array_length(v_current_edges, 1), array_length(v_base_route_edges, 1)));
        END IF;

        -- If diverse enough or base route, add to results
        IF v_route_count = 0 OR v_diversity >= p_diversity_threshold THEN
            
            -- Important: Correct geometry orientation and segment ordering
            RETURN QUERY
            WITH ordered_path AS (
                SELECT 
                    p1.seq,
                    p1.node_id AS start_node,
                    p2.node_id AS end_node,
                    p1.edge_id
                FROM current_path p1
                JOIN current_path p2 ON p1.seq + 1 = p2.seq
                WHERE p1.edge_id > 0
            ),
            enriched AS (
                SELECT 
                    op.seq,
                    op.edge_id,
                    op.start_node AS from_node,
                    op.end_node AS to_node,
                    e.length_m AS distance_m,
                    e.speed_limit_kmh AS speed_limit,
                    -- Reverse geometry if we are traversing from target to source
                    CASE 
                        WHEN op.start_node = e.target_id THEN ST_AsGeoJSON(ST_Reverse(e.geometry))
                        ELSE ST_AsGeoJSON(e.geometry)
                    END AS geometry_json
                FROM ordered_path op
                JOIN graphs.edges e ON e.id = op.edge_id
            )
            SELECT
                v_route_count AS route_id,
                (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'edge_id', e2.edge_id,
                            'from_node', e2.from_node,
                            'to_node', e2.to_node,
                            'distance_m', e2.distance_m,
                            'speed_limit', e2.speed_limit,
                            'effective_speed', e2.speed_limit * 0.8,
                            'bearing', 0.0,
                            'geometry', e2.geometry_json::jsonb
                        )
                        ORDER BY e2.seq
                    ) 
                    FROM enriched e2
                ) AS segments,
                (SELECT SUM(e2.distance_m) FROM enriched e2) AS total_distance_m,
                (SELECT SUM(e2.distance_m / GREATEST(e2.speed_limit, 1.0)) FROM enriched e2) AS estimated_time_sec,
                v_diversity AS diversity_score,
                v_current_edges AS edge_ids;

            v_route_count := v_route_count + 1;
            -- Accumulate edges to penalize them for the next route discovery
            v_all_penalized_edges := array_cat(v_all_penalized_edges, v_current_edges);
        ELSE
            -- We apply penalties anyway to try finding something else, but if it gets too many failures we stop.
            -- To keep it simple for now, if it's not diverse, we still penalize but don't count it.
            v_all_penalized_edges := array_cat(v_all_penalized_edges, v_current_edges);
            
            -- Guard against infinite loop if we keep finding non-diverse routes
            IF v_route_count > 0 AND array_length(v_all_penalized_edges, 1) > 10000 THEN
                EXIT;
            END IF;
        END IF;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION graphs.get_k_routes_with_diversity IS 
'Calculate K alternative routes with diversity penalties and corrected geometry orientation.
Uses a penalty-based approach to discourage reusing edges from previous routes.';

