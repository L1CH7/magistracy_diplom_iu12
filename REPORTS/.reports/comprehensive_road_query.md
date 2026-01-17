# Comprehensive OSM Road Data Query

## Все теги для дорог (на основе OSM Wiki)

### 1. Базовая классификация
- `highway` - тип дороги (motorway, trunk, primary, secondary, tertiary, residential, service, unclassified, living_street)
- `name` - название
- `ref` - номер маршрута (М1, Е95)
- `oneway` - одностороннее движение (yes/no/-1)

### 2. Скорость
- `maxspeed` - максимальная скорость (60, RU:urban, RU:rural, RU:motorway)
- `maxspeed:forward` / `maxspeed:backward` - скорость по направлениям
- `maxspeed:lanes` - скорость по полосам (100|80|60)
- `maxspeed:conditional` - условная скорость (50 @ (07:00-19:00))
- `maxspeed:advisory` - рекомендуемая скорость
- `minspeed` - минимальная скорость

### 3. Полосы движения
- `lanes` - общее количество полос
- `lanes:forward` / `lanes:backward` - полосы по направлениям
- `lanes:bus:forward` - выделенные полосы для автобусов
- `turn:lanes` - назначение полос (left|through|right)
- `change:lanes` - возможность перестроения (yes|only_left|only_right)
- `width:lanes` - ширина каждой полосы
- `placement` - расположение на дороге

### 4. Физические характеристики
- `surface` - покрытие (asphalt, concrete, gravel, unpaved)
- `smoothness` - ровность (excellent, good, bad, very_bad)
- `width` - ширина проезжей части (метры)
- `lit` - освещение (yes/no)
- `lane_markings` - наличие разметки

### 5. Структурные элементы
- `bridge` - мост (yes/viaduct)
- `tunnel` - туннель (yes)
- `layer` - уровень (1/-1/0)
- `embankment` - насыпь
- `cutting` - выемка

### 6. Велосипеды и пешеходы
- `cycleway` - велополосы (track, lane, opposite_lane)
- `cycleway:left` / `cycleway:right` - велополосы слева/справа
- `sidewalk` - тротуар (left, right, both, none)
- `footway` - пешеходная дорожка

### 7. Парковка
- `parking:left` / `parking:right` - парковка (parallel, diagonal, perpendicular, no_parking)
- `parking:lane:right:width` - ширина парковки

### 8. Доступ и ограничения
- `access` - общий доступ (yes, no, private, delivery)
- `motor_vehicle` - доступ для автомобилей
- `hgv` - доступ для грузовиков
- `bicycle` - доступ для велосипедов
- `foot` - доступ для пешеходов
- `maxheight` - максимальная высота
- `maxwidth` - максимальная ширина
- `maxweight` - максимальный вес
- `maxlength` - максимальная длина

### 9. Условные ограничения
- `access:conditional` - условный доступ (destination @ (Mo-Fr 07:00-10:00))
- `maxspeed:conditional` - условная скорость
- `restriction:conditional` - условные ограничения поворотов

### 10. Светофоры (nodes)
- `highway=traffic_signals` - узел светофора
- `traffic_signals:direction` - направление (forward/backward)
- `button_operated` - кнопка активации
- `traffic_signals:sound` - звуковые сигналы
- `traffic_signals:countdown` - обратный отсчет

### 11. Пешеходные переходы (nodes)
- `highway=crossing` - пешеходный переход
- `crossing` - тип (traffic_signals, uncontrolled, island, marked, unmarked)
- `crossing:island` - островок безопасности

### 12. Дорожные знаки (nodes)
- `traffic_sign` - код знака (RU:296, RU:320)
- `direction` - направление действия знака

## Полный Overpass запрос

```overpass
[out:json][timeout:900];
(
  // Все дороги с полной информацией
  way({{bbox}})[highway~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street|pedestrian|track)$"];
  
  // Светофоры
  node({{bbox}})[highway=traffic_signals];
  
  // Пешеходные переходы
  node({{bbox}})[highway=crossing];
  
  // Дорожные знаки
  node({{bbox}})[traffic_sign];
  
  // Ограничения поворотов (relations)
  relation({{bbox}})[type=restriction];
);
// Получаем все узлы для ways
(._;>;);
out geom;
```

## Запрос для Python с использованием нашего API

Мы будем запрашивать:
1. **Ways (дороги)** - со всеми тегами
2. **Nodes (узлы)** - светофоры, переходы, знаки
3. **Relations (отношения)** - ограничения поворотов

Теги автоматически включаются в Overpass JSON ответ.
