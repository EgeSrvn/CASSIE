FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code (maintaining backend/ structure)
COPY api/ ./backend/api/

# Add backend to Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 3001

# Run FastAPI with uvicorn
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "3001"]

