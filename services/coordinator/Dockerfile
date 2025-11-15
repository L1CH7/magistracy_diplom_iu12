FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY services/coordinator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY services/coordinator/src/ ./src/
COPY configs ./configs/

# Expose port
EXPOSE 8002

# Run
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002"]
