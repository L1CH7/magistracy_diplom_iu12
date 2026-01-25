FROM python:3.11-slim as builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY services/gateway/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy service code relative to context root
COPY services/gateway/src/ ./src/
COPY services/common/ ./services/common/
COPY services/__init__.py ./services/

ENV PYTHONPATH=/app

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
