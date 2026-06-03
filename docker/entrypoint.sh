#!/bin/sh
set -e

cd /app/anchorpoint

echo "Applying database migrations..."
python manage.py migrate --noinput

# Hand off to the container command (gunicorn, by default).
exec "$@"
