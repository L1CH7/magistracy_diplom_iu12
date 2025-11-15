FROM python:3.11-slim

WORKDIR /app

# Copy service requirements
COPY services/simulation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source (from context root = project root)
COPY services/simulation/src/ ./src/
COPY src/shared ./src/shared/
COPY configs ./configs/

# Expose port
EXPOSE 8001

# Run
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
