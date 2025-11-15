FROM python:3.11-slim

WORKDIR /app

COPY services/router/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/router/src/ ./src/
COPY configs ./configs/

EXPOSE 8003

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8003"]
