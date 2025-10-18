# CI/CD, Git и Docker практики (актуально)

## Git workflow
- Используй feature branches: `feature/add-osrm-integration`, `fix/graph-loading-bug`.
- Префиксы: `feature/`, `fix/`, `refactor/`, `docs/`, `test/`.
- Формат commit message: `type(scope): description` (Conventional Commits).
  ```
  feat(routing): add OSRM integration
  fix(graph): handle disconnected nodes
  refactor(core): extract RouteEngine interface
  docs(readme): add SUMO setup instructions
  ```

## Git best practices
- Коммить часто, но атомарно: один логический change = один коммит.
- Избегай коммитов вида "fix", "wip", "asdf" — переписывай историю через `git rebase -i`.
- Используй `.gitignore` для исключения артефактов: `__pycache__/`, `*.pyc`, `.agent_dir/out/`, `*.log`.
- Никогда не коммить credentials, токены, приватные ключи.

## Branching strategy
- `main` — стабильная ветка, всегда рабочая.
- `develop` — интеграционная ветка для разработки.
- Feature branches создаются от `develop`, мержатся обратно через PR.
- Используй tags для релизов: `v0.1.0`, `v0.2.0`.

## Pull Requests
- PR должен решать одну задачу.
- Описание PR: что делает, почему, как проверить.
- Self-review перед созданием PR: прочитай diff, удали debug-код.
- Добавляй скриншоты/логи для визуальных изменений.

## CI/CD pipeline
- Используй GitHub Actions / GitLab CI.
- Stages: lint → test → build → deploy.
- **Lint stage**: ruff/black для Python, clang-format для C++.
- **Test stage**: pytest с coverage report (стремиться к >80%).
- **Build stage**: docker build + push в registry.
- **Deploy stage**: автоматический деплой в dev/staging окружение.

## Pre-commit hooks
- Используй `pre-commit` framework:
  ```yaml
  repos:
    - repo: https://github.com/psf/black
      rev: 23.3.0
      hooks:
        - id: black
    - repo: https://github.com/charliermarsh/ruff-pre-commit
      rev: v0.0.270
      hooks:
        - id: ruff
  ```

## Docker best practices
- **Multi-stage builds**: отдельные stage для build и runtime.
  ```dockerfile
  FROM python:3.11-slim AS builder
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --user --no-cache-dir -r requirements.txt

  FROM python:3.11-slim
  COPY --from=builder /root/.local /root/.local
  COPY . /app
  WORKDIR /app
  CMD ["python", "main.py"]
  ```
- Минимизируй размер образа: используй alpine/slim базы, удаляй кэши после установки.
- Используй `.dockerignore`: исключай `.git/`, `__pycache__/`, `.agent_dir/out/`.
- Тегируй образы осмысленно: `project:v0.1.0`, `project:latest`, `project:dev`.

## Docker Compose для локальной разработки
- Сервисы: `server` (FastAPI), `client` (PyQt + QtWebEngine), `db` (PostGIS), `redis` (Streams/PubSub), `valhalla` (роутинг), `tiles` (опционально).
- Используй volumes для данных БД и тайлов, монтируй X11 сокет для клиента, пробрасывай `/dev/dri` для GPU.
- Переменные окружения: `DISPLAY`, `QTWEBENGINE_DISABLE_SANDBOX=1`, `TILE_URL`.
- Пример (фрагмент):
  ```yaml
  services:
    server:
      build: ./
      environment:
        - VALHALLA_URL=http://valhalla:8002
        - REDIS_URL=redis://redis:6379
        - DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres
      depends_on: [db, redis, valhalla]

    client:
      build: ./
      environment:
        - DISPLAY
        - TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
        - QTWEBENGINE_DISABLE_SANDBOX=1
      volumes:
        - /tmp/.X11-unix:/tmp/.X11-unix
      devices:
        - /dev/dri:/dev/dri
      depends_on: [server]

    db:
      image: postgis/postgis:15-3.3
      environment:
        - POSTGRES_PASSWORD=postgres
      volumes:
        - pgdata:/var/lib/postgresql/data

    redis:
      image: redis:7

    valhalla:
      image: ghcr.io/valhalla/valhalla:latest
      # Подготовка тайлов выполняется заранее; сервис слушает 8002

  volumes:
    pgdata: {}
  ```

## Secrets management
- Никогда не хардкодь секреты в коде.
- Используй переменные окружения: `os.getenv("API_KEY")`.
- Для локальной разработки: `.env` файл (добавить в `.gitignore`).
- Для продакшена: секреты в CI/CD variables или secret managers (Vault, AWS Secrets).

## CI рекомендации для этого проекта
- Джоб lint+test на Python (ruff/pytest), сборка Docker образов `server` и `client`.
- Кэшировать зависимости pip по hash `requirements.txt`.
- Публиковать артефакты отчётов (метрики/графики) из `.agent_dir/out/` как CI artifacts.
