FROM python:3.11-slim

WORKDIR /app

COPY services/traffic-manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/traffic-manager/src/ ./src/
COPY configs ./configs/

EXPOSE 8004

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8004"]
