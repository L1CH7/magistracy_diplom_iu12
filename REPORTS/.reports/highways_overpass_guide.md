<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# мне теперь интересно получить максимум информации об авто дорогах в РФ. как это сделать с помощью overpass api? повторяюсь: нужен максимум - разметка, кол-во полос, скорость, знаки, светофоры, разрешение на повороты, перекрестки или мосты и тд. просто, вся информация. если есть ссылка на статью, где описаны все актуальные свойства - дай, я кину агенту, чтобы он работал

Отлично! У меня есть вся необходимая информация. Создам полный и подробный ответ с примерами Overpass запросов и ссылками на документацию.

## Получение максимума информации об автомобильных дорогах через Overpass API

### Полная схема OSM тегов для дорог

Все теги дорожной инфраструктуры задокументированы в **официальной документации OpenStreetMap Wiki** здесь:

**Основные ссылки на документацию:**

- **Highways (полная классификация дорог):** https://wiki.openstreetmap.org/wiki/Highways[^1]
- **Lanes (теги полос, их свойства):** https://wiki.openstreetmap.org/wiki/Lanes[^2]
- **Key:maxspeed (ограничения скорости):** https://wiki.openstreetmap.org/wiki/Key:maxspeed[^3]
- **Relation:restriction (ограничения поворотов):** https://wiki.openstreetmap.org/wiki/Relation:restriction[^4]
- **Overpass API Language Guide (примеры запросов):** https://wiki.openstreetmap.org/wiki/Overpass_API/Language_Guide[^5]

***

### Полный список тегов для дорог (категоризация)

#### **1. Классификация и основные свойства**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `highway=*` | motorway, trunk, primary, secondary, tertiary, residential, service, living_street, unclassified, track, path | Тип дороги[^1] |
| `name=*` | текст | Название дороги |
| `ref=*` | текст | Номер маршрута (например M1, A2) |
| `oneway=*` | yes, no, reversible | Одностороннее движение[^6] |
| `oneway=-1` | значение | Обратное направление одностороннего движения |

#### **2. Ограничения скорости**

| Тег | Примеры | Описание |
| :-- | :-- | :-- |
| `maxspeed=*` | 60, 100, none | Максимальная разрешённая скорость (км/ч по умолчанию)[^3] |
| `maxspeed:advisory=*` | 80 | Рекомендуемая (не обязательная) скорость[^7] |
| `maxspeed:forward=*`, `maxspeed:backward=*` | 100\|80 | Скорость в разных направлениях |
| `maxspeed:lanes=*` | 100\|80\|60 | Скорость для каждой полосы[^2] |
| `maxspeed:conditional=*` | yes @ (Mo-Fr 07:00-18:00) | Условное ограничение (время суток, дни недели) |

#### **3. Информация о полосах движения**

| Тег | Примеры | Описание |
| :-- | :-- | :-- |
| `lanes=*` | 2, 3, 4 | Общее количество полос[^2] |
| `lanes:forward=*` | 2 | Количество полос в направлении хода way |
| `lanes:backward=*` | 1 | Количество полос в обратном направлении |
| `lanes:bus:forward=*` | 1 | Выделенные полосы для автобусов |
| `lanes:taxi:forward=*` | 1 | Выделенные полосы для такси |
| `turn:lanes=*` | left\|through\|through\|right | Назначение каждой полосы (повороты)[^2] |
| `change:lanes=*` | yes\|only_left\|only_right\|yes | Возможность перестроения между полосами[^2] |
| `width:lanes=*` | 3.5\|3.5 | Ширина каждой полосы (метры) |
| `maxheight:lanes=*` | 3.5\|3.5 | Максимальная высота для каждой полосы |

#### **4. Разметка и характеристики дороги**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `surface=*` | asphalt, concrete, gravel, unpaved, paved | Покрытие дороги[^8] |
| `smoothness=*` | excellent, good, intermediate, bad, very_bad, impassable | Ровность дороги[^9] |
| `width=*` | 10.5 | Общая ширина проезжей части (метры) |
| `lit=*` | yes, no | Наличие уличного освещения |
| `lane_markings=*` | yes, no | Наличие разметки полос |

#### **5. Структура дороги (велополосы, пешеходные зоны, парковка)**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `cycleway=*` | track, lane, opposite_lane, share_busway | Велополосы или велодорожки[^10] |
| `cycleway:left=*`, `cycleway:right=*` | lane, track, opposite | Велополосы слева/справа |
| `sidewalk=*` | left, right, both, none | Наличие тротуара[^11] |
| `parking:left=*`, `parking:right=*` | parallel, diagonal, perpendicular, no_parking | Парковка слева/справа |
| `parking:lane:right:width=*` | 2.5 | Ширина парковочной зоны |

#### **6. Пересечения и переезды**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `crossing=*` | traffic_signals, uncontrolled, island, marked | Тип пешеходного переезда[^12] |
| `crossing:island=*` | yes, no | Наличие островка безопасности |
| `bridge=*` | yes, viaduct | Мост[^13] |
| `tunnel=*` | yes | Туннель |
| `ford=*` | yes, stepping_stones | Брод (переезд через воду) |
| `layer=*` | 1, -1, 0 | Слой (для пересечений: 1 - над, -1 - под) |
| `railway=level_crossing` | yes | Железнодорожный переезд |

#### **7. Светофоры и дорожные знаки**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `highway=traffic_signals` | - | Узел светофора в пересечении[^14] |
| `traffic_signals:direction=*` | forward, backward | Направление действия светофора[^15] |
| `traffic_sign=*` | RU:296, RU:320 | Код дорожного знака (страна:код)[^16] |
| `traffic_signs:operating_times=*` | Mo-Su 07:00-22:00 | Время работы светофора |

#### **8. Ограничения доступа и поворотов**

| Тег | Значения | Описание |
| :-- | :-- | :-- |
| `access=*` | yes, no, private, delivery, destination | Общее ограничение доступа[^17] |
| `motor_vehicle=*` | yes, no, destination | Доступ для автомобилей |
| `hgv=*` | yes, no | Доступ для грузовиков |
| `hov=*` | 2, 3 | Минимальное количество людей в авто для использования полосы[^2] |
| `bicycle=*` | yes, no, designated | Доступ для велосипедов |
| `foot=*` | yes, no, designated | Доступ для пешеходов |

#### **9. Ограничения размеров и веса**

| Тег | Примеры | Описание |
| :-- | :-- | :-- |
| `maxheight=*` | 3.5 | Максимальная высота (метры) |
| `maxwidth=*` | 2.6 | Максимальная ширина (метры) |
| `maxweight=*` | 7.5 | Максимальный вес (тонны) |
| `maxlength=*` | 18 | Максимальная длина (метры) |

#### **10. Условные ограничения (по времени, дням недели)**

| Тег | Примеры | Описание |
| :-- | :-- | :-- |
| `access:conditional=*` | destination @ (Mo-Fr 07:00-10:00) | Условный доступ |
| `maxspeed:conditional=*` | 50 @ (rain) | Скорость при определённых условиях |
| `restriction:conditional=*` | no_left_turn @ (Mo-Fr 07:00-18:00) | Условное ограничение поворотов |


***

### Ограничения поворотов (Turn Restrictions)

Ограничения поворотов хранятся в **отношениях (relations)** с типом `restriction`:[^18][^4]

```
type=restriction
restriction=no_left_turn | no_right_turn | no_u_turn | only_left_turn | only_right_turn | only_straight_on
```

**Структура:**

- `from` - дорога, с которой приезжаете
- `via` - узел пересечения
- `to` - дорога, на которую едите

**Запрос ограничений поворотов:**

```
[out:json][timeout:25];
area["name"="Москва"]->.a;
relation["type"="restriction"](area.a);
out body geom;
```


***

### Полные примеры Overpass QL запросов для России

#### **1. Все дороги в регионе с полной информацией**

```
[out:json][timeout:900];
area["name"="Московская область"]->.a;
way(area.a)["highway"~"motorway|trunk|primary|secondary|tertiary|residential|unclassified"]
["highway"!~"path|footway|cycleway|bridleway|steps|proposed|construction"];
(._;>;);
out geom;
```


#### **2. Дороги с разметкой полос и ограничениями скорости**

```
[out:json][timeout:900];
area["name"="Санкт-Петербург"]->.a;
way(area.a)["highway"]["lanes"]["maxspeed"];
(._;>;);
out geom;
```


#### **3. Дороги с поворотных ограничениями и светофорами**

```
[out:json][timeout:900];
(
  relation["type"="restriction"](area:3600001);
  way(r)["highway"]~"motorway|trunk|primary|secondary";
  node["highway"="traffic_signals"](area:3600001);
);
(._;>;);
out geom;
```


#### **4. Дороги с пешеходными переездами и велополосами**

```
[out:json][timeout:900];
area["name"="Москва"]->.a;
(
  way(area.a)["cycleway"]~"track|lane|opposite_lane";
  node(area.a)["crossing"]~"traffic_signals|uncontrolled";
  way(area.a)["sidewalk"]~"left|right|both";
);
(._;>;);
out geom;
```


#### **5. Полная информация о дороге (максимум данных)**

```
[out:json][timeout:900];
area["name"="Тюмень"]->.a;
way(area.a)["highway"];
(._;
  node(area.a)["highway"="traffic_signals"];
  relation["type"="restriction"](area.a);
  >
;);
out geom;
```


***

### Важные замечания для России

**Использование Overpass для РФ:**

1. **ID регионов РФ:** Для запроса по областям используйте `area["name"="..."]` или OSM relation ID + 3600000000[^19]
2. **Примеры ID для больших городов:**
    - Москва: ID 3600000001
    - Санкт-Петербург: ID 3600000002
3. **Формат максимальной скорости в России:** `maxspeed=RU:urban` (автоматическое определение скорости)[^3]
4. **Сервер с быстрым доступом из РФ:**

```
https://maps.mail.ru/osm/tools/overpass/api/interpreter
```

5. **Условные ограничения (важно для РФ):**

```
maxspeed:conditional=50 @ (Mo-Fr 07:00-19:00)
restriction:conditional=no_left_turn @ (Mo-Fr 08:00-18:00)
```


***

### Инструменты для работы

- **Overpass Turbo:** https://overpass-turbo.eu/ - визуальный редактор запросов
- **Python библиотека:** `pip install overpy` - для работы с данными в коде[^20]
- **JOSM:** Редактор для проверки и добавления тегов на месте

Все документация актуальна и поддерживается сообществом OpenStreetMap.[^12][^1][^2][^4][^3]
<span style="display:none">[^21][^22][^23][^24][^25][^26][^27][^28][^29][^30][^31][^32][^33][^34][^35][^36][^37][^38][^39][^40]</span>

<div align="center">⁂</div>

[^1]: https://wiki.openstreetmap.org/wiki/Highways

[^2]: https://wiki.openstreetmap.org/wiki/Lanes

[^3]: https://wiki.openstreetmap.org/wiki/Key:maxspeed

[^4]: https://wiki.openstreetmap.org/wiki/Relation:restriction

[^5]: https://wiki.openstreetmap.org/wiki/Overpass_API/Language_Guide

[^6]: https://wiki.openstreetmap.org/wiki/Tag:oneway=reversible

[^7]: https://wiki.openstreetmap.org/wiki/Key:maxspeed:advisory

[^8]: https://wiki.openstreetmap.org/wiki/Key:surface

[^9]: https://wiki.openstreetmap.org/wiki/Key:smoothness

[^10]: https://wiki.openstreetmap.org/wiki/Key:cycleway

[^11]: https://wiki.openstreetmap.org/wiki/Key:sidewalk

[^12]: https://wiki.openstreetmap.org/wiki/Tag:crossing=traffic_signals

[^13]: https://wiki.openstreetmap.org/wiki/Key:bridge

[^14]: https://wiki.openstreetmap.org/wiki/Tag:highway=traffic_signals

[^15]: https://wiki.openstreetmap.org/wiki/Key:traffic_signals:direction

[^16]: https://wiki.openstreetmap.org/wiki/Key:traffic_sign

[^17]: https://wiki.openstreetmap.org/wiki/OSM_tags_for_routing/Access_restrictions

[^18]: https://wiki.openstreetmap.org/wiki/JOSM_Relations_and_Turn_Based_Restrictions

[^19]: https://gist.github.com/JamesChevalier/b861388d35476cee4fcc3626a60af60f?permalink_comment_id=3082448

[^20]: https://python-overpy.readthedocs.io/en/latest/api.html

[^21]: https://stackoverflow.com/questions/31795115/query-overpass-api-for-highways-and-corresponding-nodes

[^22]: https://docs.google.com/document/d/1isc9M9_c-QL4Oy8_MxAyogZ6ocs1F6PeEn_Y1p0WZp8/mobilebasic

[^23]: https://www.reddit.com/r/openstreetmap/comments/s20rtk/how_to_query_multiple_tags_at_once_in_overpass/

[^24]: https://wiki.openstreetmap.org/wiki/United_States_roads_tagging

[^25]: https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_API_by_Example

[^26]: https://wiki.openstreetmap.org/wiki/Key:highway

[^27]: https://wiki.openstreetmap.org/wiki/Tag:restriction=no_right_turn_on_red

[^28]: https://wiki.openstreetmap.org/wiki/Key:ford

[^29]: https://wiki.openstreetmap.org/wiki/Conditional_restrictions

[^30]: https://community.openstreetmap.org/t/how-to-tag-road-crossing-river-that-is-not-bridge-or-ford/4141

[^31]: https://wiki.openstreetmap.org/wiki/Tag:restriction=no_u_turn

[^32]: https://stackoverflow.com/questions/38922898/how-to-get-only-the-nearby-subset-of-a-ways-nodes

[^33]: https://wiki.openstreetmap.org/wiki/Tag:cycleway=sidewalk

[^34]: https://community.openstreetmap.org/t/revision-of-smoothness-gallery/123273

[^35]: https://wiki.openstreetmap.org/wiki/RU:Key:surface

[^36]: https://josm.openstreetmap.de/wiki/Help/Plugin/TurnRestrictions

[^37]: https://dev.overpass-api.de/overpass-doc/en/criteria/misc_criteria.html

[^38]: https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL

[^39]: https://www.reddit.com/r/openstreetmap/comments/2hj2nv/how_do_relations_work/

[^40]: https://www.reddit.com/r/openstreetmap/comments/w0jtk0/overpass_turbo_how_to_limit_query_by_state_name/

