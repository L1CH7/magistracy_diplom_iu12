FROM python:3.11-slim

WORKDIR /app

COPY services/data-processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/data-processor/src/ ./src/
COPY configs ./configs/
COPY data ./data/

EXPOSE 8005

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8005"]
