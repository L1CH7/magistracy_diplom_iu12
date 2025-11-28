-- Migration 004: Create graphs.edges table (routing graph)
-- Date: 2025-11-28
-- Purpose: Store routing edges with pgRouting compatibility

CREATE TABLE graphs.edges (
    -- ========== pgRouting REQUIRED columns ==========
    id SERIAL PRIMARY KEY,
    source INT NOT NULL REFERENCES graphs.nodes(id),
    target INT NOT NULL REFERENCES graphs.nodes(id),
    
    -- ========== GEOMETRY & LENGTH ==========
    geom GEOMETRY(LineString, 4326) NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,  -- Вычисляется в TRIGGER!
    
    -- ========== OSM SOURCE ==========
    osm_way_id BIGINT,
    osm_tags JSONB,
    
    -- ========== ROAD ATTRIBUTES ==========
    highway VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    lanes INT DEFAULT 1,
    oneway BOOLEAN DEFAULT false,
    
    bearing_start FLOAT,
    bearing_end FLOAT,
    
    -- ========== SPEED (computed in TRIGGER!) ==========
    maxspeed_kmh INT,
    -- Устанавливается GraphBuilder с дефолтами по highway
    -- Приоритет: OSM > config > DEFAULT_SPEEDS[highway]
    -- NULL допустим, будет применен дефолт в apply_default_speeds()
    
    unstamped_speed_kmh INT,
    -- maxspeed_kmh + tolerance (из config, например +19 для РФ)
    -- Вычисляется в TRIGGER, NULL если maxspeed_kmh NULL
    
    -- ========== ACCESS & RESTRICTIONS ==========
    access_type VARCHAR(50) DEFAULT 'public',
    motor_vehicle VARCHAR(50),
    service VARCHAR(50),
    barrier_penalty_sec INT DEFAULT 0,
    
    -- ========== TRAFFIC & CAPACITY (computed in TRIGGER!) ==========
    capacity INT,
    -- Формула: (length_m * lanes) / (v_ms * safe_distance_s + length_auto_m)
    -- где v_ms = unstamped_speed_kmh * 0.2777 (км/ч -> м/с)
    -- Вычисляется в TRIGGER из конфигов system_config
    -- Может быть NULL до apply_default_speeds(), затем заполняется fallback
    
    current_load INT DEFAULT 0,
    -- Обновляется симуляцией в реальном времени
    
    -- ========== DYNAMIC FIELDS (GENERATED ALWAYS STORED) ==========
    -- ⚠️ ТОЛЬКО эти пересчитываются при изменении current_load!
    -- BPR функция: скорость падает квадратично при приближении к capacity
    
    cost DOUBLE PRECISION GENERATED ALWAYS AS (
        -- pgRouting cost в секундах (BPR congestion function)
        CASE 
            WHEN capacity IS NULL OR unstamped_speed_kmh IS NULL THEN NULL  -- Еще не заполнено
            WHEN capacity = 0 THEN 1000000  -- Защита от деления на 0
            ELSE length_m / (
                GREATEST(5.0,  -- Минимум 5 км/ч (затор)
                    unstamped_speed_kmh::FLOAT * 
                    (1.0 - POWER(current_load::FLOAT / capacity::FLOAT, 2))
                ) / 3.6
            )
        END
    ) STORED,
    
    reverse_cost DOUBLE PRECISION GENERATED ALWAYS AS (
        -- pgRouting reverse_cost: -1 if oneway
        CASE 
            WHEN oneway THEN -1.0
            WHEN capacity IS NULL OR unstamped_speed_kmh IS NULL THEN NULL
            WHEN capacity = 0 THEN 1000000
            ELSE length_m / (
                GREATEST(5.0,
                    unstamped_speed_kmh::FLOAT * 
                    (1.0 - POWER(current_load::FLOAT / capacity::FLOAT, 2))
                ) / 3.6
            )
        END
    ) STORED,
    
    -- ========== METADATA ==========
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Uniqueness: same OSM way can produce multiple edges (split at intersections)
    UNIQUE(osm_way_id, source, target)
);

-- ==================== INDEXES ====================
CREATE INDEX idx_edges_source ON graphs.edges(source);
CREATE INDEX idx_edges_target ON graphs.edges(target);
CREATE INDEX idx_edges_geom ON graphs.edges USING GIST(geom);
CREATE INDEX idx_edges_highway ON graphs.edges(highway);
CREATE INDEX idx_edges_cost ON graphs.edges(cost);

-- ==================== COMMENTS ====================
COMMENT ON TABLE graphs.edges IS 'Routing graph edges (roads split at intersections)';
COMMENT ON COLUMN graphs.edges.source IS 'pgRouting: start node ID';
COMMENT ON COLUMN graphs.edges.target IS 'pgRouting: end node ID';
COMMENT ON COLUMN graphs.edges.length_m IS 'Length in meters (computed in TRIGGER)';
COMMENT ON COLUMN graphs.edges.maxspeed_kmh IS 'Speed limit (OSM > config > default)';
COMMENT ON COLUMN graphs.edges.unstamped_speed_kmh IS 'Unstamped speed: maxspeed + tolerance (computed in TRIGGER)';
COMMENT ON COLUMN graphs.edges.capacity IS 'Max vehicles on edge: (length*lanes)/(v*safe_dist+car_len) (computed in TRIGGER)';
COMMENT ON COLUMN graphs.edges.current_load IS 'Current traffic load (updated by simulation)';
COMMENT ON COLUMN graphs.edges.cost IS 'pgRouting cost in seconds with BPR congestion (GENERATED)';
COMMENT ON COLUMN graphs.edges.reverse_cost IS 'pgRouting reverse cost: -1 if oneway (GENERATED)';
