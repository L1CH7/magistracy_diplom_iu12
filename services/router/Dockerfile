FROM python:3.11-slim

WORKDIR /app

# Оптимизация pip с BuildKit mount cache
COPY services/router/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

# Копируем весь проект (нужен для импортов src/routing/, services/router/)
COPY . .

# Создаём директорию для логов
RUN mkdir -p logs

EXPOSE 8003

CMD ["uvicorn", "services.router.src.main:app", "--host", "0.0.0.0", "--port", "8003"]
