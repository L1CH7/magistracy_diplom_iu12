### 📋 MASTER PROMPT: Технический отчет о реализации (Strict Engineering Report)

**Роль:** Ведущий системный архитектор / Автор технической документации.
**Задача:** Написать главу "Архитектура, Проблематика и Реализация" для магистерской диссертации.
**Язык:** Строгий академический русский.

---

### 1. Требования к стилю и оформлению (Style Guide)

* **Запрещено:** Эмодзи, спецсимволы, маркетинговые клише ("революционный", "уникальный"), риторические вопросы.
* **Запрещено:** Избыточные англицизмы и дублирование перевода (Пример ошибки: "Поток данных (Data Flow)"). Используйте устоявшиеся русские термины (архитектура, латентность, конкурентность) или оригинал, если аналога нет (High-Load, Overhead).
* **Запрещено:** Выводы ("Заключение") в конце каждого подраздела. Текст должен быть связным повествованием.
* **Формулы:** Использовать LaTeX (например, ).
* **Диаграммы:** Использовать Mermaid в стандартном стиле (без кастомных цветов и стилизации).
* **Тон:** Критический, честный инженерный анализ. Мы не продаем продукт, мы защищаем технические решения и признаем компромиссы. 
* **Учти:** Пусть мы и не продаем работу, мне всегда говорили - "рассказывай так словно это самая лучшая работа в мире", потому даже если "отрицательный результат - результат" - это хорошо.

---

### 2. Контекст и Фактура (Обязательно к использованию)

Используй следующие факты, выявленные в ходе исследования (Deep Research) и разработки:

**А. Анализ аналогов и выбор технологии**
Мы сравнивали OSRM, Valhalla, GraphHopper и Custom pgRouting.

* **Аналоги (In-Memory движки):**
* *Плюс:* Хранят граф в RAM, отклик <10 мс.
* *Минус:* Невозможность динамически менять веса (пробки, погода) или накладывать сложные штрафы (Turn Penalties) без полной перестройки графа.


* **Наш выбор (pgRouting + Custom Python):**
* *Причина:* Требование гибкости. Нам нужно сочетать K-маршрутов, ограничения поворотов и динамические веса.
* *Компромисс:* Мы жертвуем латентностью (I/O с диска) ради гибкости SQL-запросов.


Анализ Аналогов и Выбор Технологии (Почему мы страдаем?)
Мы рассматривали OSRM, Valhalla, GraphHopper.

Плюсы аналогов: Они хранят граф постоянно в RAM (In-Memory). Это дает отклик <10мс.

Минусы аналогов: Они "жесткие". Ты не можешь на лету изменить вес одного ребра, не перестраивая граф часами.

Почему мы выбрали свой движок (Custom pgRouting):

Нам нужна гибкость: сочетание Turn Penalties (штрафы за повороты) + Dynamic Weights (пробки/погода) + K-маршрутов через N точек.

Ключевая проблема: В pgRouting нет "серебряной пули". Функции типа pgr_ksp (Yen's algorithm) не поддерживают Turn Restrictions (TRSP) адекватно. Ты либо получаешь K маршрутов, но с нарушением ПДД, либо 1 маршрут по правилам.

Решение: Писать свою логику оркестрации поверх атомарных функций БД.



**Б. Проблема построения графа (Build Phase)**

* **Проблема:** Стандартная функция `pgr_nodeNetwork` на графе Москвы (250k ребер) потребляет >12 ГБ RAM и падает (OOM) из-за гигантских геометрий (МКАД).
* **Решение:** Алгоритм "Плиточной нарезки" (Grid Partitioning).
* Предварительная нарезка линий (`ST_Subdivide`).
* Обработка квадратами по 0.05 градуса.
* **Результат:** Снижение потребления RAM с 12 ГБ до **370 МБ**. Время сборки: 13 минут.


Проблема Построения Графа (The Build Phase Nightmare)
Исходная ситуация: Стандартная функция pgr_nodeNetwork — это "черный ящик". На графе Москвы (250k ребер) она пожирала 12GB+ RAM и падала (OOM) или уходила в своп.

Причина: Попытка загрузить гигантские геометрии (были куски по 9км одной линией) в память.

Наше решение (Deep Research Result):

Grid Partitioning (Плиточная нарезка): Мы написали свой скрипт, который режет карту на квадраты 0.05 градуса.

Subdivide: Предварительная физическая нарезка линий.

Результат: Граф строится за 13 минут (вместо часов/сбоев) с потреблением 370 МБ RAM. Это победа архитектуры над грубой силой.

```
docker exec diplom-router-1 python -c "import psycopg2; conn = psycopg2.connect(host='postgis', user='postgres', password='postgres', dbname='nav_mas'); cur = conn.cursor(); cur.execute(\"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP(ORDER BY length_m) as median, PERCENTILE_CONT(0.75) WITHIN GROUP(ORDER BY length_m) as p75, PERCENTILE_CONT(0.90) WITHIN GROUP(ORDER BY length_m) as p90, PERCENTILE_CONT(0.99) WITHIN GROUP(ORDER BY length_m) as p99, MAX(length_m) as max_len, AVG(length_m) as avg_len, COUNT(*) as count FROM graphs.edges\"); stats = cur.fetchone(); print(f'Stats from graphs.edges (Count: {stats[6]}):'); print(f'  Median: {stats[0]:.2f}m'); print(f'  75%:    {stats[1]:.2f}m'); print(f'  90%:    {stats[2]:.2f}m'); print(f'  99%:    {stats[3]:.2f}m'); print(f'  Max:    {stats[4]:.2f}m'); print(f'  Avg:    {stats[5]:.2f}m'); print('\nTop 10 Longest Edges:'); cur.execute(\"SELECT id, length_m, osm_way_id FROM graphs.edges ORDER BY length_m DESC LIMIT 10\"); [print(f'  ID: {r[0]}, Len: {r[1]:.2f}m, OSM: {r[2]}') for r in cur.fetchall()];"

Stats from graphs.edges (Count: 228818):

  Median: 70.46m

  75%:    153.24m

  90%:    297.51m

  99%:    841.80m

  Max:    8373.13m

  Avg:    127.18m



Top 10 Longest Edges:

  ID: 218687, Len: 8373.13m, OSM: 697054

  ID: 19851, Len: 7061.81m, OSM: 530958

  ID: 224898, Len: 6164.42m, OSM: 719243

  ID: 218778, Len: 6087.02m, OSM: 697057

  ID: 172076, Len: 6049.51m, OSM: 530963

  ID: 113312, Len: 5720.55m, OSM: 423799

  ID: 114980, Len: 5600.99m, OSM: 530376

  ID: 113341, Len: 5529.86m, OSM: 423842

  ID: 27228, Len: 5270.69m, OSM: 407098

  ID: 155601, Len: 4847.44m, OSM: 622097
```

в итоге стало:
```
Stats from edge_candidates (Count: 244305):

  Median: 78.13m

  75%:    165.82m

  90%:    294.98m

  99%:    517.23m

  Max:    871.64m

  Avg:    119.18m



Top 10 Longest Edges:

  ID: 369644, Len: 871.64m

  ID: 564239, Len: 831.69m

  ID: 515871, Len: 819.99m

  ID: 445240, Len: 780.64m

  ID: 445240, Len: 780.64m

  ID: 424235, Len: 769.96m

  ID: 725519, Len: 760.74m

  ID: 405013, Len: 752.79m

  ID: 405013, Len: 752.79m

  ID: 419563, Len: 748.04m
```
**В. Эволюция алгоритмов (Runtime)**

* **A* (A-Star):** Отказ. Требует тяжелых `JOIN` с таблицей узлов для эвристики, что перегружает CPU базы данных.
* **KSP (Yen's Algorithm):** Отказ. Возвращает топологически идентичные маршруты (отличие в 1 сегмент). Не поддерживает сложные ограничения.
* **Итоговое решение:** Iterative Penalty Dijkstra.
1. Найти путь.
2. Увеличить стоимость ребер пути (x5).
3. Повторить поиск.


* Это дает реальное разнообразие маршрутов.

Алгоритмическая Эволюция (Runtime Struggle)
Мы прошли через несколько стадий боли:

A* (A-Star): Провал. Теоретически быстр, но в PostgreSQL требует тяжелых JOIN с таблицей узлов для эвристики. CPU улетал в 100%.

pgr_ksp (K-Shortest Paths): Провал.

Выдает 3 почти одинаковых маршрута (отличие в 1 сегмент).

Не умеет работать со сложными ограничениями (Turn Penalties).

Очень медленный на больших графах.

Iterative Penalty Dijkstra (Наше решение):

Запускаем быструю Дейкстру.

Берем ребра пути, умножаем их Cost на 5.0 (штраф).

Запускаем снова.

Это дает реально разные маршруты и позволяет учитывать любые ограничения.


**Г. Честная производительность**

* **Stateless архитектура:** pgRouting не хранит состояние в RAM. Каждый запрос — это чтение с диска/кэша ОС.
* **Цифры:** "Чистое" время SQL-запроса — 40–100 мс. Полное время ответа (Cold Start, Network, Parsing) может достигать **6–10 секунд** на сложных маршрутах. Это "узкое место" системы (I/O Bound).

Честная Производительность (The Harsh Reality)
Не пиши маркетинговую чушь про "10 мс".

Проблема архитектуры: pgRouting Stateless. Он не хранит граф в RAM. При каждом запросе (транзакции) Postgres должен поднять данные с диска (или из Shared Buffers) в память процесса.

Реальные цифры:

"Чистый" расчет алгоритма (SQL time): 40-100 мс (если данные в кэше).

Cold Start / End-to-End Latency: Полный цикл (HTTP -> Python -> Connect DB -> Load Graph Pages -> Calc -> Fetch -> Parse WKB -> HTTP) занимает 6-10 секунд на сложных маршрутах.

Вывод: Это плата за гибкость и возможность работать на слабом железе (Low RAM), но это узкое место для High-Load (50 потоков кладут диск/IO).

**Д. Достижения UX (Quality of Life)**

WKB вместо GeoJSON: Перешли на бинарный формат, ускорили парсинг в Python в разы.

Smart Snapping: Заменили привязку к "ближайшей линии" (которая магнитит к мостам над головой) на KNN-поиск "ближайшего узла графа".

Zig-Zag Fix: Реализовали проверку направления геометрии (CASE WHEN node=source...), чтобы маршрут не рисовал петли.

---

### 3. Структура Главы

1. **Сравнительный анализ технологий:** Таблица (OSRM vs Valhalla vs Наше решение). Обоснование выбора (Flexibility over Latency).
2. **Справочник функций (Glossary):** Таблица ключевых функций pgRouting, используемых в проекте (название, назначение, почему используем или почему отказались).
* *Пример:* `pgr_dijkstra`, `pgr_ksp`, `pgr_nodeNetwork`.


3. **Архитектура хранения (Build Phase):** Проблема OOM и решение через Grid Partitioning.
4. **Алгоритмы маршрутизации (Runtime):**
* Почему Дейкстра с BBOX лучше, чем A*.
* Проблема разнообразия маршрутов и решение через итеративные штрафы.


5. **Качество данных и UX:**
* Переход на WKB (бинарный формат).
* Исправление визуальных артефактов ("Зиг-заги").
* *Важно:* Реализация Snapping (привязки к графу).


6. **Честный анализ производительности:** Плюсы и минусы Stateless-подхода.
7. **Планы по доработке:**
* отказ от готовых технологий и написание собственного алгоритма маршрутизации на C++ (например Boost::Graph).
* Кэширование "горячих" участков графа в RAM (warm-up). Или даже полный перенос в ОЗУ, тк граф сам по себе небольшой.
* добавление штрафов за повороты.
* добавление динамических весов.
* Внедрение полноценного Contraction Hierarchies для магистралей или иные оптимизации роутинга.



---

### 4. ПРОТОКОЛ ВЕРИФИКАЦИИ (Strict Audit)

**Ты обязан сверять текст отчета с реальным кодом/конфигурацией.**

1. **Проверка KNN (Snapping):**
* В отчетах упоминается "Vertex Snapping через KNN". **ПРОВЕРЬ КОД** (`snap_to_road`).
* Если в коде используется поиск ближайшего ребра (`graphs.edges`), а не узла (`graphs.nodes`), ты **ОБЯЗАН** написать в отчете правду: *"Было протестировано решение с KNN, но в текущей версии используется привязка к ребру из-за [причина]..."* или *"KNN находится в планах доработки"*. Не выдумывай функционал, которого нет в коде.


2. **Проверка Jaccard:**
* Если фильтрация Жаккара не реализована в коде (нет функции с `numpy` или `set` intersections), не упоминай если у нас принципиально иной алгоритм


3. **Цифры:**
* Если бенчмарки показывают 6 секунд, а текст говорит про "мгновенно" — пиши про 6 секунд. Честность важнее красоты.

или если сказать иначе:
TRICT VERIFICATION PROTOCOL (The "Truth Police" Layer)
CRITICAL INSTRUCTION: Do NOT blindly trust the provided text summaries. You must act as a Code Auditor. Your goal is to compare the Narrative (what we claimed) against the Evidence (what is actually in the code/config).

Mandatory Verification Steps:

Code vs. Claims Check:

Example (KNN Snapping): The report claims we switched to "Vertex Snapping via KNN" (graphs.nodes). CHECK THE CODE in pgrouting_engine.py (specifically snap_to_road). Does it actually query graphs.nodes? Or does it still query graphs.edges? If the code uses graphs.edges, you MUST correct the report to reflect reality (e.g., "Attempted KNN, but reverted to Edge Snapping due to X" or "KNN is architectural plan").

Example (Performance): The report claims "10-40ms latency", but the benchmarks also mention "6-10 seconds" for cold starts. You must explicitly highlight this discrepancy. Do not hide the slow parts.

Evidence Citation:

Every major technical claim must be backed by a reference to a file or a specific line of code.

Format: "We implemented WKB ... (see pgrouting_engine.py: ST_AsBinary usage)".

If you mention docker-compose settings (like shm_size: 4gb), confirm they exist in the configuration context.

Identify "Phantom" Features:

If the text mentions a feature (like "Jaccard Filtering" or "KNN") but you cannot find the implementation logic in the provided code snippets, label it as "Theoretical Design" or "Proposed Improvement", not "Implemented Feature".

Tone Adjustment:

Be skeptical. If a metric looks too good to be true (like "instant routing" on a 50-thread load), qualify it with the hardware constraints (e.g., "SQL execution is fast, but I/O latency dominates").

Explicitly list Tech Debt: What is missing? (e.g., "The current KSP implementation lacks true diversity because...")

Output Requirement: For every major section of the report, add a "Verification Status" block:

✅ Verified (Code matches description)

⚠️ Discrepancy (Code does X, Report says Y) -> Correction provided

❌ Missing Evidence (Feature mentioned but code not found)


**Вывод:** Создай профессиональный, технически выверенный текст, готовый для вставки в дипломную работу.

