# Руководство по запуску проекта

Дата: 2025-10-19

Этот документ описывает минимальные шаги для сборки и запуска демо (R-D-1) и подготовку окружения под будущие фазы (R-D-2).

## Требования
- Linux host с X11 (для клиентского QtWebEngine)
- Docker и Docker Compose
- Видеодрайвер с доступом к /dev/dri (опционально, для GPU-ускорения)

## Переменные окружения
- DISPLAY — унаследовать из хоста
- TILE_URL — URL тайлов (по умолчанию OSM: https://tile.openstreetmap.org/{z}/{x}/{y}.png)
- QTWEBENGINE_DISABLE_SANDBOX=1 — для работы QtWebEngine внутри контейнера

## Быстрый старт (демо без PostGIS/Valhalla)

1) Убедиться, что на хосте разрешён доступ X11 для контейнера (локально):
```zsh
xhost +local:root
```

2) Собрать и запустить docker-compose c сервером и клиентом:
```zsh
docker compose up --build -d
```

3) Клиент откроет окно с картой. Проверьте контекстное меню и построение маршрута.

## Включение GPU-ускорения
- В docker-compose для клиента должны быть проброшены:
  - volumes: /tmp/.X11-unix:/tmp/.X11-unix
  - devices: /dev/dri:/dev/dri
  - env: DISPLAY, QTWEBENGINE_DISABLE_SANDBOX=1

## Подготовка scaffold сервисов (R-D-2)

- PostGIS: будет добавлен в docker-compose как `db` c образом postgis/postgis.
- Redis: как `redis` (Streams/PubSub) для телеметрии и событий.
- Valhalla: как `valhalla` (роутинг), проксируется сервером.

Подробный план и аргументация — в `.github/ARCHITECTURE_OPTIONS.md` и `.github/ROUTING_SIMULATION.md`.

## Траблшутинг
- Ошибка `libGL.so.1 not found` в клиентском контейнере — добавьте системные либы в образ: libgl1, libxkbcommon-x11-0, libnss3, libasound2.
- Черное окно вместо карты — проверьте DISPLAY и права X11 (`xhost`), проверьте TILE_URL.
- Нет маршрута — проверьте доступность серверного эндпоинта /route и корректность координат.
