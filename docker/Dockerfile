FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY docker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy gunicorn config
COPY docker/gunicorn.conf.py ./gunicorn.conf.py

# Create directories for static and media files
RUN mkdir -p /app/anchorpoint/staticfiles /app/anchorpoint/media

# Collect static files (requires a dummy SECRET_KEY at build time)
WORKDIR /app/anchorpoint
RUN SECRET_KEY=build-time-placeholder python manage.py collectstatic --noinput --clear

EXPOSE 8000

# Run with gunicorn using config file
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "anchorpoint.wsgi:application"]
