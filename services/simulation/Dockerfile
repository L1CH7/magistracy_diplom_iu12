FROM python:3.11-slim

WORKDIR /app

# Оптимизация pip с BuildKit mount cache
COPY services/simulation/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

# Копируем исходники
COPY services/simulation/src/ ./src/
COPY src/shared ./src/shared/
COPY src/utils ./src/utils/

EXPOSE 8001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
