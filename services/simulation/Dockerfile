FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

# Copy shared code from project root
COPY ../../src/shared ./src/shared
COPY ../../configs ./configs

# Expose port
EXPOSE 8001

# Run
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
