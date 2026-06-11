FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
# ffmpeg transcodes uploaded/recorded audio to MP3 for Twilio phone blasts.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    fonts-dejavu-core \
    libusb-1.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY docker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy gunicorn config
COPY docker/gunicorn.conf.py ./gunicorn.conf.py

# Entrypoint applies DB migrations before the app server starts. sed strips any
# CR characters so the script runs on Linux even if checked out with CRLF on
# Windows.
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Scheduler loop used by the cron sidecar service (see docker-compose.yml).
COPY docker/cron.sh /app/cron.sh
RUN sed -i 's/\r$//' /app/cron.sh && chmod +x /app/cron.sh

# Create directories for static and media files
RUN mkdir -p /app/anchorpoint/staticfiles /app/anchorpoint/media

# Collect static files (requires a dummy SECRET_KEY at build time)
WORKDIR /app/anchorpoint
RUN SECRET_KEY=build-time-placeholder python manage.py collectstatic --noinput --clear

EXPOSE 8000

# Migrations run here (entrypoint) before gunicorn (CMD) takes over.
ENTRYPOINT ["/app/entrypoint.sh"]

# Run with gunicorn using config file
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "anchorpoint.wsgi:application"]
