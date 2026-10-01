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

# Processes run as an unprivileged `app` user. as-app.sh starts as root only to
# hand the media volume to `app`, then drops privileges (setpriv) before
# running migrations, gunicorn, or the cron loop.
COPY docker/as-app.sh /app/as-app.sh
RUN sed -i 's/\r$//' /app/as-app.sh && chmod +x /app/as-app.sh \
    && useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin app

# Create directories for static and media files
RUN mkdir -p /app/anchorpoint/staticfiles /app/anchorpoint/media \
    && chown app:app /app/anchorpoint/media

# Collect static files (requires a dummy SECRET_KEY at build time)
WORKDIR /app/anchorpoint
RUN SECRET_KEY=build-time-placeholder python manage.py collectstatic --noinput --clear

EXPOSE 8000

# Drop to `app`, then run migrations (entrypoint.sh) before gunicorn (CMD).
ENTRYPOINT ["/app/as-app.sh", "/app/entrypoint.sh"]

# Run with gunicorn using config file
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "anchorpoint.wsgi:application"]
