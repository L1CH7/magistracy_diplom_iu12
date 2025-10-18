# Рабочий процесс дипломного проекта (актуально)

## Общая структура работы

Магистерская диссертация включает **4 этапа исследования**:
1. **R&D-1**: Базовая архитектура и прототип (1 агент, PyQt+MapLibre, REST /route).
2. **R&D-2**: Расширенная система с координатором (WS, Valhalla+PostGIS, Redis Streams/PubSub; SUMO — опционально).
3. **R&D-3**: Масштабирование и промышленная готовность.
4. **R&D-Thesis**: Финализация, оформление диссертации, защита.

## Git стратегия

### Основные ветки

- **master** (главная, стабильная)
  - Содержит только **проверенный, рабочий код**.
  - Слияние происходит после завершения очередного этапа R&D.
  - Каждый merge в master = milestone проекта.
  - Тегируется: `v0.1.0-rd1`, `v0.2.0-rd2`, и т.д.

- **R&D-1** (первый этап исследования)
  - План-минимум: базовая архитектура, SUMO интеграция, простой координатор.
  - Содержит рабочий код текущего этапа.
  - После достижения целей → merge в master.

- **R&D-2** (второй этап)
  - План-максимум: RL-координатор, динамический маршрутизатор.
  - Создаётся от master после завершения R&D-1.

- **R&D-3** (третий этап)
  - Масштабирование, оптимизация, промышленные эксперименты.

- **R&D-Thesis** (финальный этап)
  - Оформление диссертации, финальные правки кода.
  - Подготовка презентации, публикации.

### Feature branches (опционально)

Для крупных фич внутри этапа можно создавать временные ветки:
- `feature/rl-coordinator` → merge в R&D-2.
- `fix/graph-disconnected-nodes` → merge в текущую R&D ветку.
- `refactor/routing-interface` → merge в текущую R&D ветку.

После merge feature branch удаляется.

### Рабочий процесс

1. **Начало нового этапа**:
   ```bash
   git checkout master
   git pull
   git checkout -b R&D-2
   git push -u origin R&D-2
   ```

2. **Ежедневная работа**:
   ```bash
   git checkout R&D-1
   # ... работаем, коммитим ...
   git add .
   git commit -m "feat(coordination): add SimpleCoordinator"
   git push
   ```

3. **Завершение этапа**:
   ```bash
   # Убедись, что всё работает, тесты проходят
   pytest tests/

   # Merge в master
   git checkout master
   git merge R&D-1 --no-ff -m "Merge R&D-1: базовая архитектура готова"
   git tag v0.1.0-rd1
   git push --tags
   git push
   ```

### Что коммитить

**Коммитим**:
- Исходный код (src/).
- Тесты (tests/).
- Конфигурации (configs/).
- Документацию (docs/, README.md).
- LaTeX отчёты (docs/latex/).
- Скрипты (scripts/).
- Docker файлы (docker/, docker-compose.yml).
- Зависимости (requirements.txt, pyproject.toml).

**НЕ коммитим** (добавить в .gitignore):
- `.agent_dir/out/` — артефакты экспериментов.
- `.agent_dir/logs/` — логи выполнения.
- `__pycache__/`, `*.pyc` — Python кэш.
- `*.log` — логи.
- `.env` — переменные окружения.
- Большие датасеты (OSM файлы > 100MB) — хранить отдельно, ссылку в README.

### Примеры хороших commit messages

```
feat(routing): add SUMO duarouter integration
fix(graph): handle disconnected nodes in OSM data
refactor(coordination): extract Coordinator interface
docs(readme): add SUMO setup instructions
test(routing): add integration tests for SUMORouteEngine
perf(graph): optimize Dijkstra with priority queue
chore(deps): update stable-baselines3 to 2.1.0
```

## Материалы для РПЗ (REPORTS)

Структура каталога `REPORTS/`:

```
REPORTS/
├── architecture/
│   ├── mas_concept.md               # Концепция МАС
│   └── system_architecture.md       # (ссылки на .github/*.md, диаграммы)
├── roadmap.md                       # Этапы R-D-1/R-D-2
├── experiments.md                   # Методика экспериментов и метрики
└── references.md                    # Список источников и аналогов
```

Полезные «симлинки» (указываем пути):
- .github/ARCHITECTURE_OPTIONS.md — сравнение опций и консенсус.
- .github/ROUTING_SIMULATION.md — выбор роутинга/симуляции и realtime.
- .github/02-architecture-and-design.md — архитектурные принципы и контракты.
- .github/05-navigation-mas-project.md — формулировка задачи и планы.

## LaTeX отчёт

### Структура отчёта

```
docs/latex/
├── main.tex                    # Главный файл
├── chapters/
│   ├── 01-introduction.tex     # Введение
│   ├── 02-literature-review.tex# Обзор литературы
│   ├── 03-methodology.tex      # Методология
│   ├── 04-implementation.tex   # Реализация
│   ├── 05-experiments.tex      # Эксперименты
│   └── 06-conclusion.tex       # Заключение
├── figures/                    # Графики, диаграммы
├── tables/                     # Таблицы результатов
├── bibliography.bib            # Библиография
└── Makefile                    # Сборка отчёта
```

### Компиляция отчёта

**Локально**:
```bash
cd docs/latex
make pdf
```

**Через Docker**:
```bash
docker run --rm -v $(pwd)/docs/latex:/work texlive/texlive:latest   bash -c "cd /work && pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex"
```

### Автоматизация через команду

Агент может компилировать отчёт по команде:
```bash
python scripts/build_report.py
```

Скрипт должен:
1. Собрать актуальные метрики из `.agent_dir/out/`.
2. Обновить таблицы и графики в `docs/latex/tables/` и `docs/latex/figures/`.
3. Скомпилировать LaTeX → PDF.
4. Вывести путь к готовому PDF.

## Ведение TODO и прогресса

### TODO.md

Формат TODO списка в `.agent_dir/TODO.md`:

```markdown
# TODO для R&D-1

## Высокий приоритет
- [ ] Реализовать OSMLoader для загрузки данных через Overpass
- [ ] Конвертировать OSM в граф NetworkX
- [ ] Настроить SUMO docker контейнер

## Средний приоритет
- [ ] Написать SimpleCoordinator
- [ ] Добавить логирование метрик
- [~] Реализовать SUMORouteEngine (в процессе)

## Низкий приоритет
- [ ] Оптимизировать загрузку графа (если будет время)
- [ ] Добавить веб-интерфейс для визуализации

## Завершено
- [x] Создать структуру проекта
- [x] Настроить pytest
- [x] Добавить pre-commit hooks
```

Обозначения:
- `[ ]` — не выполнено.
- `[~]` — в процессе выполнения.
- `[x]` — завершено.

### PROGRESS.md

Формат файла достижений в `.agent_dir/PROGRESS.md`:

```markdown
# Прогресс по R&D-1

## Достигнутые результаты

### 2025-10-09
- ✅ Создана базовая структура проекта
- ✅ Настроен CI/CD pipeline (GitHub Actions)
- ✅ Реализован OSMLoader: загрузка данных Москвы (10km²)

### 2025-10-15
- ✅ GraphBuilder: конвертация OSM → NetworkX граф (1500 узлов, 3200 рёбер)
- ✅ SUMORouteEngine: интеграция с duarouter через TraCI
- ⚠️ Найдены disconnected nodes (15 шт.) → добавлена обработка

### 2025-10-20
- ✅ SimpleCoordinator: равномерное распределение агентов по K маршрутам
- ✅ Первая симуляция: 50 агентов, avg_time=320s (baseline), 280s (simple)
- 📊 Baseline: все на кратчайший маршрут → затор на ул. Тверская

## Текущая проблема
- SUMO duarouter работает медленно для 100+ агентов (>5s на пересчёт)
- Рассматриваю переход на custom Dijkstra с кэшированием

## Следующие шаги
- [ ] Профилирование SUMO: где узкое место?
- [ ] Реализовать CustomDijkstraEngine для сравнения
- [ ] Собрать метрики для 100, 500 агентов
```

### Автоматическое обновление

Агент должен:
1. После каждого значимого результата обновлять PROGRESS.md.
2. Переносить завершённые задачи из TODO.md в PROGRESS.md.
3. Добавлять timestamp и краткое описание достижения.

## Сохранение контекста между сессиями

### Использование MCP memory-bank

При завершении рабочей сессии агент должен:
1. Сохранить текущий контекст в memory-bank:
   - Что было сделано сегодня.
   - Какие проблемы возникли.
   - Следующие шаги.

2. При начале новой сессии:
   - Восстановить контекст из memory-bank.
   - Прочитать TODO.md и PROGRESS.md.
   - Предложить план работы на сессию.

### Checkpoint файлы

Для длительных экспериментов (обучение RL) сохранять checkpoints:
```
.agent_dir/checkpoints/
├── rl_model_epoch_100.pt
├── rl_model_epoch_200.pt
└── best_model.pt
```

С метаданными:
```
.agent_dir/checkpoints/metadata.json
{
  "epoch_100": {
    "timestamp": "2025-10-20T15:30:00",
    "reward": -45.2,
    "avg_time": 280
  }
}
```

## Метрики и отчётность

### Автоматический сбор метрик

После каждого эксперимента сохранять:
```
.agent_dir/out/experiments/
├── exp_001_baseline.json
├── exp_002_simple.json
└── exp_003_rl.json
```

Формат JSON:
```json
{
  "experiment_id": "exp_001_baseline",
  "timestamp": "2025-10-20T16:00:00",
  "method": "baseline",
  "num_agents": 50,
  "metrics": {
    "avg_travel_time": 320.5,
    "max_edge_load": 0.85,
    "throughput": 48
  },
  "config": {
    "map": "moscow_center",
    "graph_size": {"nodes": 1500, "edges": 3200}
  }
}
```

### Генерация графиков

Агент должен автоматически генерировать:
- Line plot: avg_time vs num_agents для разных методов.
- Bar plot: сравнение методов по метрикам.
- Heatmap: загрузка сети по времени симуляции.

Сохранять в:
```
.agent_dir/out/figures/
├── avg_time_comparison.png
├── metrics_comparison.png
└── network_heatmap.png
```

Эти графики копировать в `docs/latex/figures/` для отчёта.

## Чеклист перед завершением этапа R&D

Перед merge в master проверить:

- [ ] Все тесты проходят: `pytest tests/ --cov`
- [ ] Линтер не выдаёт ошибок: `ruff check src/`
- [ ] Форматирование кода: `black src/ tests/`
- [ ] Type hints проверены: `mypy src/`
- [ ] Документация актуальна: README.md описывает как запустить текущий функционал
- [ ] LaTeX отчёт обновлён: добавлены результаты текущего этапа
- [ ] TODO.md: все задачи этапа завершены или перенесены
- [ ] PROGRESS.md: описаны достижения этапа
- [ ] Docker контейнеры собираются: `docker-compose build`
- [ ] Integration test проходит: полный цикл от загрузки данных до симуляции
- [ ] Метрики собраны и сохранены в `.agent_dir/out/`
- [ ] Tag создан: `git tag v0.X.0-rdN`

## Публикации и защита

### План публикаций

- **R&D-1 → R&D-2**: тезисы на конференцию (российскую).
- **R&D-2 → R&D-3**: статья в журнал (ВАК / Scopus).
- **R&D-Thesis**: финальная статья + диссертация.

### Структура статьи

1. Abstract
2. Introduction (проблема, актуальность)
3. Related Work (обзор аналогов)
4. Methodology (описание подхода)
5. Experiments (эксперименты, метрики)
6. Results and Discussion
7. Conclusion

Агент может помочь:
- Генерировать черновики разделов на основе кода и метрик.
- Создавать таблицы результатов в LaTeX.
- Строить графики для статьи.

## Работа с научным руководителем

### Регулярные встречи

- Каждые 2-3 недели.
- Перед встречей: обновить PROGRESS.md, подготовить вопросы.
- После встречи: зафиксировать решения в TODO.md.

### Формат отчёта для руководителя

Краткий отчёт (1-2 страницы):
```markdown
# Отчёт по R&D-1 (период 01.10 - 20.10)

## Выполнено
- Реализована загрузка OSM данных
- Интеграция с SUMO
- SimpleCoordinator показывает улучшение на 12% относительно baseline

## Проблемы
- SUMO duarouter медленный для >100 агентов
- Рассматриваю custom Dijkstra

## Следующие шаги
- Профилирование и оптимизация
- Эксперименты с 500 агентами
- Начало работы над RL-координатором

## Вопросы
1. Достаточно ли улучшения 12% для публикации?
2. Можно ли использовать синтетические данные вместо OSM?
```

Сохранять в `.agent_dir/reports/supervisor/`.

## Резервное копирование

### Важные артефакты

Регулярно делать backup:
- `.agent_dir/out/experiments/` → облако (Google Drive / Yandex Disk).
- `docs/latex/` → коммитить в Git.
- Обученные модели (`*.pt`, `*.pth`) → облако, если >100MB.

### Автоматизация

Создать скрипт `scripts/backup.sh`:
```bash
#!/bin/bash
timestamp=$(date +%Y%m%d_%H%M%S)
tar -czf backup_$timestamp.tar.gz .agent_dir/out docs/latex
# Upload to cloud...
```

Запускать еженедельно или после значимых экспериментов.
