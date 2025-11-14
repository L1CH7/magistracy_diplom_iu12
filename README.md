# Navigation MAS

Сервер-координатор + GUI клиент для навигации, маршрутизации и симуляции агентов.

## Архитектура

**Client**: PyQt5 + MapLibre GL JS с аппаратным ускорением для рендеринга векторных карт  
**Server**: FastAPI + PostgreSQL/PostGIS для хранения графов и MVT tiles  
**Routing**: A*/Dijkstra (планируется миграция на pgRouting)  
**Simulation**: собственная симуляция агентов с динамическим capacity и FPS-контролем  
**Configuration**: YAML с hot reload и директивой !include для композиции конфигов  
**Logging**: Loguru + Grafana + Loki для сбора логов и метрик  

## Quick Start

### Docker run (рекомендуется)
```bash
docker-compose up --build
```
Клиент на порту 5000, сервер на 8000, Grafana на 3000.

### Local run
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd src/server && uvicorn app:app --reload &
cd src/client && python main.py
```

## Ключевые фичи

- **MVT Tiles**: граф дорог хранится как векторные тайлы ST_AsMVT, рендерится в реальном времени MapLibre
- **LOD System**: 4-слойная прогрессивная детализация (z0-10: магистрали, z14+: все дороги)
- **Hot Reload**: редактируй YAML конфиги → перезапусти контейнер (без rebuild)
- **Include Directive**: `map.yaml` включает `map.lod.yaml` + `map.rendering.yaml` через `!include`
- **Simulation**: динамические веса рёбер (capacity), FPS-контроль, детект телепортаций
- **k-shortest paths**: построение нескольких лучших маршрутов
- **PostGIS Integration**: хранение графов, тайлов, bbox-запросы
- **Grafana Monitoring**: логи и метрики производительности (время маршрутизации, загрузка данных)

## Структура

```
configs/                     # YAML конфиги с hot reload
  client/                    # gui, data, simulation, map (+ LOD/rendering)
  server/                    # api, database, routing
  common.yaml, regions.yaml
src/
  client/                    # PyQt5 GUI + MapLibre
    ui/widgets/map_widget.py # интеграция MapLibre GL через QWebEngineView
    services/                # API клиенты, async workers
    handlers/                # обработчики событий карты
  server/app.py              # FastAPI endpoints (/route, /tiles/road, /graph)
  data/                      # OSM Overpass, graph builder, PostGIS
  routing/                   # route_engine.py (A*/Dijkstra)
  simulation/agent.py        # агент с capacity-aware движением
  utils/config_loader.py     # ConfigLoader с !include и hot reload
```

## Конфигурация

Все параметры в `configs/*.yaml`. Примеры:

**LOD фильтрация** (`configs/client/map.lod.yaml`):
```yaml
lod_layers:
  - zoom_range: [0, 10]
    highways: [motorway, trunk, primary]  # только магистрали
  - zoom_range: [14, 22]
    highways: [motorway, trunk, primary, secondary, tertiary, residential, service]  # всё
```

**Симуляция** (`configs/client/simulation.yaml`):
```yaml
speed:
  min: 0.1
  max: 10.0
  default: 1.0
fps: 20
agent:
  look_ahead_steps: 3
```

Изменил конфиг → `docker-compose restart client` → изменения применены.

## Следующие шаги (НИР-2)

- Миграция на pgRouting для динамической маршрутизации
- Выделение агента как отдельной сущности (без GUI)
- Координатор для управления тысячами агентов
- Админ-клиент для мониторинга
- Масштабирование симуляции (целевое требование: 1000+ агентов)
