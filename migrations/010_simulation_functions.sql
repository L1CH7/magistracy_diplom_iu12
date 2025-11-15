-- Function: Load graph data for SimulationManager
-- Returns edge data in format ready for GraphCache

CREATE OR REPLACE FUNCTION graphs.get_simulation_graph()
RETURNS TABLE(
    edge_id BIGINT,
    source_node BIGINT,
    target_node BIGINT,
    length_m FLOAT,
    speed_limit_kmh INTEGER,
    bearing_start FLOAT,
    bearing_end FLOAT,
    capacity INTEGER,
    start_lon FLOAT,
    start_lat FLOAT,
    end_lon FLOAT,
    end_lat FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.id AS edge_id,
        e.source AS source_node,
        e.target AS target_node,
        e.length_m,
        e.maxspeed_kmh AS speed_limit_kmh,
        e.bearing_start,
        e.bearing_end,
        e.capacity,
        ST_X(ST_StartPoint(e.geom)) AS start_lon,
        ST_Y(ST_StartPoint(e.geom)) AS start_lat,
        ST_X(ST_EndPoint(e.geom)) AS end_lon,
        ST_Y(ST_EndPoint(e.geom)) AS end_lat
    FROM graphs.edges e
    WHERE e.geom IS NOT NULL
      AND e.length_m > 0
    ORDER BY e.id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION graphs.get_simulation_graph() IS 
'Loads complete graph for simulation. Returns all edges with geometry endpoints, bearing, capacity.';


-- Function: Update edge loads (batch)
-- Called by SimulationManager every 1-5 seconds

CREATE OR REPLACE FUNCTION graphs.batch_update_edge_loads(
    edge_loads JSONB  -- Format: [{"edge_id": 123, "current_load": 45}, ...]
)
RETURNS VOID AS $$
BEGIN
    UPDATE graphs.edges e
    SET 
        current_load = (load_data->>'current_load')::INTEGER,
        updated_at = NOW()
    FROM jsonb_array_elements(edge_loads) AS load_data
    WHERE e.id = (load_data->>'edge_id')::BIGINT;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION graphs.batch_update_edge_loads(JSONB) IS
'Batch update edge current_load. Input format: [{"edge_id": 123, "current_load": 45}, ...]';


-- Function: Update effective speeds based on current_load
-- Implements BPR formula: effective_speed = speed_limit * (1 - alpha * (congestion^beta))

CREATE OR REPLACE FUNCTION graphs.update_effective_speeds(
    alpha FLOAT DEFAULT 0.7,
    beta FLOAT DEFAULT 1.5,
    min_speed_kmh FLOAT DEFAULT 5.0
)
RETURNS INTEGER AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE graphs.edges
    SET effective_speed = CASE
        -- No load → full speed
        WHEN current_load = 0 THEN maxspeed_kmh
        
        -- Low congestion (< 50% capacity) → near full speed
        WHEN current_load::FLOAT / NULLIF(capacity, 0) < 0.5 THEN maxspeed_kmh
        
        -- Moderate to high congestion → BPR formula
        WHEN current_load::FLOAT / NULLIF(capacity, 0) < 1.0 THEN
            GREATEST(
                min_speed_kmh,
                maxspeed_kmh * (1.0 - alpha * POWER(current_load::FLOAT / capacity, beta))
            )
        
        -- Overcapacity → minimum speed (gridlock)
        ELSE GREATEST(min_speed_kmh, maxspeed_kmh * 0.1)
    END
    WHERE current_load > 0 OR effective_speed IS NULL;
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION graphs.update_effective_speeds(FLOAT, FLOAT, FLOAT) IS
'Update effective_speed for all edges based on current_load. Uses BPR formula from Highway Capacity Manual.';


-- Function: Get congestion statistics (for monitoring)

CREATE OR REPLACE FUNCTION graphs.get_congestion_stats()
RETURNS TABLE(
    total_edges BIGINT,
    edges_with_load BIGINT,
    edges_over_capacity BIGINT,
    avg_congestion FLOAT,
    max_congestion FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT AS total_edges,
        COUNT(*) FILTER (WHERE current_load > 0)::BIGINT AS edges_with_load,
        COUNT(*) FILTER (WHERE current_load > capacity)::BIGINT AS edges_over_capacity,
        AVG(current_load::FLOAT / NULLIF(capacity, 1))::FLOAT AS avg_congestion,
        MAX(current_load::FLOAT / NULLIF(capacity, 1))::FLOAT AS max_congestion
    FROM graphs.edges
    WHERE capacity > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION graphs.get_congestion_stats() IS
'Returns congestion statistics for monitoring/telemetry.';
