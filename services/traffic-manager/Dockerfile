FROM python:3.11-slim

WORKDIR /app

# Оптимизация pip с BuildKit mount cache
COPY services/traffic-manager/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

# Копируем исходники
COPY services/traffic-manager/src/ ./src/

EXPOSE 8004

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8004"]
