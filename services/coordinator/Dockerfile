FROM python:3.11-slim

WORKDIR /app

# Оптимизация pip с BuildKit mount cache
COPY services/coordinator/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

# Копируем исходники
COPY services/coordinator/src/ ./src/

EXPOSE 8002

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002"]
