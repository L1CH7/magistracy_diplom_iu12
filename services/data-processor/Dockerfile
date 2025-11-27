FROM python:3.11-slim

WORKDIR /app

# Оптимизация pip с BuildKit mount cache
COPY services/data-processor/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

# Копируем исходники service
COPY services/data-processor/src/ ./src/

# Копируем общие утилиты (osm_overpass, graph_builder, etc)
COPY src/utils ./src/utils/

EXPOSE 8005

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8005"]
