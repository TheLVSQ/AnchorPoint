#!/bin/sh
set -e

cd /app/anchorpoint

echo "Applying database migrations..."
python manage.py migrate --noinput
# Shared cache table for rate limits / kiosk lockout (idempotent).
python manage.py createcachetable

# Hand off to the container command (gunicorn, by default).
exec "$@"
