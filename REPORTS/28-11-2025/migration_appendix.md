<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# ты меня вообще не понял? дай нормальный гайд. capacity - тоже внешняя формула. и логично же: вычисляется она из безопасной дистанции, макс скорости, полос, длины.

в graph дорога osm way делится на участки между перекрестками и еще чем-то - это просто операция построения графа. далее триггер нам вычислит длину участка length_m. внутри триггером определена разрешенная скорость и нештрафуемая скорость. в общем, capacity = length_m lanes /( unstamped_speed_kmh * 3600/1000 * safe_distance_s + length_auto_m) где length_auto_m=5 (в конфиг) safe_distance_s=3(в конфиг НО может быть функцией от unstamped_speed_kmh - и тогда в питон видимо вывод, но должно быть легко и быстро. пока пример как константу 3с из конфига)

и так со всеми моментами. generated тоже надо умно использовать, или не использовать если это накладно (если только stored тк на каждый select неудобно - лучше на update чего-то). и оставить возможность масштабироваться на много агентов когда от current load в сравнении с capacity будет вычисляться скорость потока и уменьшаться, модулируя затор

Я вас понял. Вы правы, я упустил вашу специфическую формулу `capacity` (которая у вас зависит от *безопасной дистанции* и *длины авто*, а не просто табличное значение) и желание сделать это максимально конфигурируемым, но "близко к данным" (в БД).

Вот **нормальный, жесткий гайд**, который реализует именно вашу логику:

1. **Конфиги (YAML)** — управляют константами.
2. **Таблица конфигов в БД** — мост между YAML и SQL.
3. **Триггеры** — вычисляют `length`, `unstamped_speed`, `capacity` (один раз при вставке).
4. **Generated Stored** — только для `cost/effective_speed` (пересчет при пробках).

Это **самая оптимальная архитектура**: тяжелая математика считается 1 раз при построении графа, а динамика работает на лету.

***

# 🛠️ Hardcore Guide: Graph Architecture \& Configs

**Цель:** Максимальная производительность pgRouting + Гибкость формул через конфиги.
**Принцип:** "Вычисляем тяжелое один раз (Триггеры), динамику обновляем автоматически (Generated Stored)".

***

## 1. 📄 Внешние Конфиги (YAML)

Мы не хардкодим числа в SQL. Мы создаем файлы конфигурации, которые **загружаются в БД при старте приложения**.

### `traffic_config.yaml`

```yaml
# Константы для формулы Capacity
vehicle_physics:
  length_auto_m: 5.0          # Средняя длина машины
  safe_distance_s: 3.0        # Безопасный интервал (сек)
  conversion_factor: 0.2777   # 1000/3600 (км/ч -> м/с)

# Правила скорости (региональные)
speed_rules:
  current_region: "RU"        # Используемый профиль
  profiles:
    RU:
      tolerance_kmh: 19       # +19 км/ч нештрафуемый
    BY:
      tolerance_kmh: 9
    TR:
      tolerance_percent: 0.1  # 10% (сложнее логика, пока возьмем аддитивную для примера)

# Дефолтные скорости (если нет в OSM)
default_speeds:
  motorway: 110
  city: 60
  living_street: 20
```


***

## 2. 🌉 Мост: Таблица Конфигурации в БД

Чтобы триггеры могли использовать значения из YAML, мы создаем системную таблицу. `GraphBuilder` при старте читает YAML и делает `INSERT/UPDATE` в эту таблицу.

**Миграция: `002_create_system_config.sql`**

```sql
CREATE TABLE graphs.system_config (
    key_name TEXT PRIMARY KEY,
    value_numeric NUMERIC,
    value_text TEXT
);

-- Пример данных (заполняется из Python):
-- ('length_auto_m', 5.0, NULL)
-- ('safe_distance_s', 3.0, NULL)
-- ('speed_tolerance', 19.0, NULL)
```


***

## 3. 🏗️ Структура Графа (`graphs.edges`)

Здесь реализуем вашу логику полей.

**Миграция: `004_create_edges_table.sql`**

```sql
CREATE TABLE graphs.edges (
    id SERIAL PRIMARY KEY,
    source BIGINT NOT NULL REFERENCES graphs.nodes(id),
    target BIGINT NOT NULL REFERENCES graphs.nodes(id),
    geom GEOMETRY(LineString, 4326) NOT NULL,

    -- 1. Статические данные (из OSM или Python Builder)
    highway VARCHAR(50),
    lanes INT DEFAULT 1,
    maxspeed_kmh INT NOT NULL,  -- Заполняется Builder'ом (OSM или default)
    oneway BOOLEAN DEFAULT false,

    -- 2. Вычисляемые ТРИГГЕРОМ (один раз при вставке/изменении геометрии/правил)
    length_m DOUBLE PRECISION NOT NULL,
    unstamped_speed_kmh INT NOT NULL,     -- maxspeed + tolerance
    capacity INT NOT NULL,                -- Ваша формула вместимости ребра

    -- 3. Динамика (обновляется симулятором)
    current_load INT DEFAULT 0,

    -- 4. GENERATED STORED (для pgRouting, авто-пересчет при смене current_load)
    -- BPR функция: скорость падает, если load приближается к capacity
    effective_speed_kmh DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE
            WHEN current_load = 0 THEN unstamped_speed_kmh::FLOAT -- Едем быстро
            WHEN capacity = 0 THEN 5.0                            -- Защита от деления на 0
            ELSE GREATEST(5.0,
                unstamped_speed_kmh::FLOAT * (1.0 - (current_load::FLOAT / capacity::FLOAT)^2)
            )
            -- ^ Пример квадратичного замедления. Можно упростить до линейного.
        END
    ) STORED,

    -- Cost для Dijkstra (время в секундах)
    cost DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE WHEN effective_speed_kmh <= 0 THEN 1000000 -- Затор
        ELSE length_m / (effective_speed_kmh / 3.6)
        END
    ) STORED,

    reverse_cost DOUBLE PRECISION GENERATED ALWAYS AS (
        CASE WHEN oneway THEN -1.0 ELSE cost END
    ) STORED,
    
    UNIQUE(source, target, osm_way_id)
);
```


***

## 4. ⚡ Главный Триггер: Ваша Формула

Самое важное. Триггер берет параметры из `system_config` и считает `capacity` по вашей формуле.

**Миграция: `006_create_calculation_trigger.sql`**

```sql
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

    -- 2. Получаем конфиги (они закэшированы Postgres, это быстро)
    SELECT value_numeric INTO _len_auto FROM graphs.system_config WHERE key_name = 'length_auto_m';
    SELECT value_numeric INTO _safe_dist FROM graphs.system_config WHERE key_name = 'safe_distance_s';
    SELECT value_numeric INTO _tolerance FROM graphs.system_config WHERE key_name = 'speed_tolerance';

    -- Fallbacks если конфиг пуст (на всякий случай)
    IF _len_auto IS NULL THEN _len_auto := 5.0; END IF;
    IF _safe_dist IS NULL THEN _safe_dist := 3.0; END IF;
    IF _tolerance IS NULL THEN _tolerance := 0; END IF;

    -- 3. Вычисляем нештрафуемую скорость
    NEW.unstamped_speed_kmh := NEW.maxspeed_kmh + _tolerance;

    -- 4. Вычисляем CAPACITY по вашей формуле
    -- capacity = (length * lanes) / (v_ms * safe_dist + len_auto)
    -- v_ms = speed_kmh * 0.2777

    _v_ms := NEW.unstamped_speed_kmh * 0.2777;

    -- Защита от деления на ноль (если пробка мертвая, v=0, capacity = length/len_auto)
    IF (_v_ms * _safe_dist + _len_auto) = 0 THEN
        NEW.capacity := (NEW.length_m * COALESCE(NEW.lanes, 1)) / _len_auto;
    ELSE
        NEW.capacity := (NEW.length_m * COALESCE(NEW.lanes, 1)) / (_v_ms * _safe_dist + _len_auto);
    END IF;

    -- Минимум 1 машина, чтобы не ломать логику
    IF NEW.capacity < 1 THEN NEW.capacity := 1; END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_calculate_edge_attributes
BEFORE INSERT OR UPDATE OF geom, maxspeed_kmh, lanes ON graphs.edges
FOR EACH ROW
EXECUTE FUNCTION graphs.calculate_edge_attributes();
```


***

## 5. 🐍 Python Logic (GraphBuilder)

Python здесь выполняет роль оркестратора. Он не считает формулы для каждой линии (это делает БД), он готовит среду.

**Алгоритм работы:**

1. **Загрузка Config:**
`GraphBuilder` читает `traffic_config.yaml`.
2. **Sync Config to DB:**
Выполняет `INSERT INTO graphs.system_config ... ON CONFLICT UPDATE` для всех ключей из YAML.
3. **Обработка Графа (Splitting):**
Берет OSM Way, находит перекрестки, режет линию на сегменты (Edges).
4. **Вставка Edges:**
Делает `INSERT INTO graphs.edges (geom, maxspeed_kmh, lanes, ...)`.
*Важно:* Python **НЕ** считает `length`, `capacity` или `unstamped`. Он вставляет только сырые данные (геометрию, знаки скорости, полосы).
5. **Магия:**
Срабатывает `BEFORE INSERT TRIGGER` → БД сама идет в конфиг-таблицу, берет +19, берет 3с, считает формулу и записывает итог в строку.

***

## 6. 🚀 Оптимизация и Масштабирование

### Почему это оптимально?

1. **Триггер (Static Calc):** `capacity` и `length` считаются 1 раз при создании карты. При SELECT запросах маршрутизации процессор не тратит время на формулы.
2. **Generated Stored (Dynamic Calc):** `cost` пересчитывается *автоматически*, но только когда симулятор обновляет `current_load`.
    * Если у вас 1000 агентов, вы делаете `UPDATE edges SET current_load = ... WHERE id IN (...)`.
    * Postgres тут же обновляет `cost` на диске.
    * Следующий `pgr_dijkstra` сразу видит новые веса (пробки).
3. **Масштабирование:**
    * Модель "затора" (BPR функция внутри `effective_speed`) позволяет агентам автоматически объезжать загруженные ребра, так как `cost` растет.
    * Вам не нужно перестраивать граф. Просто обновляйте `current_load`.

### Что в итоге в файле?

Я положу этот гайд рядом с миграциями. Это полная инструкция по применению вашей формулы внутри БД.

**Резюме:**

* Формула `capacity` — в **PL/pgSQL Триггере**.
* Константы (5м, 3с, +19кмч) — в **YAML** -> **Table `system_config`**.
* Скорость потока — в **GENERATED ALWAYS AS STORED** (зависит от `current_load`).

Это полностью соответствует вашему требованию: гибкий конфиг, сложная формула вместимости, автоматический учет пробок.

