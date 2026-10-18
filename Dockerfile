# Dockerfile for Google Cloud Run deployment
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Set work directory
WORKDIR /app

# Install system dependencies if any needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Initialize demo database during container build if desired
RUN python -c "from database import init_db; init_db()"

# Expose port
EXPOSE 8080

# Run with Gunicorn on 0.0.0.0 and PORT env variable
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 "app:create_app()"
