-- Migration 006: Create TRIGGER functions for edges
-- Date: 2025-11-28
-- Purpose: Auto-compute length_m, unstamped_speed, capacity from config

-- ==================== TRIGGER 1: Compute all edge attributes ==========
CREATE OR REPLACE FUNCTION graphs.calculate_edge_attributes()
RETURNS TRIGGER AS $$
DECLARE
    _len_auto NUMERIC;
    _safe_dist NUMERIC;
    _tolerance NUMERIC;
    _v_ms NUMERIC;
BEGIN
    -- 1. Вычисляем длину (геометрия)
    NEW.length_m := ST_Length(ST_Transform(NEW.geom, 3857));

    -- 2. Получаем конфиги (кэшируются Postgres)
    SELECT value_numeric INTO _len_auto FROM graphs.system_config WHERE key_name = 'length_auto_m';
    SELECT value_numeric INTO _safe_dist FROM graphs.system_config WHERE key_name = 'safe_distance_s';
    SELECT value_numeric INTO _tolerance FROM graphs.system_config WHERE key_name = 'speed_tolerance_kmh';

    -- Fallbacks если конфиг пуст
    IF _len_auto IS NULL THEN _len_auto := 5.0; END IF;
    IF _safe_dist IS NULL THEN _safe_dist := 3.0; END IF;
    IF _tolerance IS NULL THEN _tolerance := 19; END IF;

    -- 3. Вычисляем нештрафуемую скорость
    IF NEW.maxspeed_kmh IS NOT NULL THEN
        NEW.unstamped_speed_kmh := NEW.maxspeed_kmh + _tolerance;
    ELSE
        NEW.unstamped_speed_kmh := NULL;
    END IF;

    -- 4. Вычисляем CAPACITY по формуле безопасной дистанции
    -- capacity = (length * lanes) / (v_ms * safe_dist + len_auto)
    -- v_ms = speed_kmh * 0.2777 (км/ч -> м/с)
    
    IF NEW.unstamped_speed_kmh IS NOT NULL THEN
        _v_ms := NEW.unstamped_speed_kmh * 0.2777;
    ELSE
        -- Fallback: если нет maxspeed, используем дефолт 50 км/ч
        _v_ms := (50 + _tolerance) * 0.2777;
        NEW.unstamped_speed_kmh := 50 + _tolerance;
    END IF;

    -- Защита от деления на ноль
    IF (_v_ms * _safe_dist + _len_auto) = 0 THEN
        NEW.capacity := CEIL(NEW.length_m * COALESCE(NEW.lanes, 1) / _len_auto);
    ELSE
        NEW.capacity := CEIL((NEW.length_m * COALESCE(NEW.lanes, 1)) / (_v_ms * _safe_dist + _len_auto));
    END IF;

    -- Минимум 1 машина
    IF NEW.capacity < 1 THEN NEW.capacity := 1; END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_calculate_edge_attributes
BEFORE INSERT OR UPDATE OF geom, maxspeed_kmh, lanes ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION graphs.calculate_edge_attributes();

COMMENT ON FUNCTION graphs.calculate_edge_attributes IS 'Auto-compute length_m, unstamped_speed, capacity from system_config';

-- ==================== TRIGGER 2: Update timestamp ==========
CREATE OR REPLACE FUNCTION graphs.update_edge_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_updated_at_trigger
BEFORE UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION graphs.update_edge_timestamp();

COMMENT ON FUNCTION graphs.update_edge_timestamp IS 'Auto-update updated_at timestamp';

-- ==================== TRIGGER 3: Validate consistency ==========
CREATE OR REPLACE FUNCTION graphs.validate_edge_consistency()
RETURNS TRIGGER AS $$
BEGIN
    -- Проверка 1: source != target
    IF NEW.source = NEW.target THEN
        RAISE EXCEPTION 'Edge cannot start and end at the same node: %', NEW.id;
    END IF;
    
    -- Проверка 2: length_m > 0
    IF NEW.length_m <= 0 THEN
        RAISE EXCEPTION 'Edge length must be > 0: %', NEW.id;
    END IF;
    
    -- Проверка 3: maxspeed_kmh > 0
    IF NEW.maxspeed_kmh <= 0 THEN
        RAISE EXCEPTION 'maxspeed_kmh must be > 0: %', NEW.id;
    END IF;
    
    -- Проверка 4: capacity > 0
    IF NEW.capacity <= 0 THEN
        RAISE EXCEPTION 'capacity must be > 0: %', NEW.id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER edge_validate_trigger
BEFORE INSERT OR UPDATE ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION graphs.validate_edge_consistency();

COMMENT ON FUNCTION graphs.validate_edge_consistency IS 'Validate edge consistency (source != target, length > 0, etc.)';
