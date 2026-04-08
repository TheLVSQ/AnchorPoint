#!/usr/bin/env bash
# AnchorPoint deployment script
# Run this on the droplet to pull latest code and restart services.
# Called automatically by GitHub Actions on push to main.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f $REPO_DIR/docker/docker-compose.yml"

log() { echo "[deploy] $*"; }

log "Pulling latest code from main..."
git -C "$REPO_DIR" fetch origin main
git -C "$REPO_DIR" reset --hard origin/main

log "Building images..."
$COMPOSE build --pull --quiet

log "Starting services..."
$COMPOSE up -d --remove-orphans

log "Waiting for web container to be healthy..."
timeout 60 bash -c "until $COMPOSE ps web | grep -q 'healthy'; do sleep 2; done" \
  || { log "WARNING: health check timed out, continuing anyway"; }

log "Running migrations..."
$COMPOSE exec -T web python manage.py migrate --noinput

log "Collecting static files..."
$COMPOSE exec -T web python manage.py collectstatic --noinput --clear

log "Pruning unused Docker images..."
docker image prune -f --filter "until=24h" >/dev/null

log "Deploy complete."
