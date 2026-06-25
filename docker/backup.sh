#!/bin/sh
# Daily Postgres backup sidecar.
#
# Dumps the AnchorPoint database to /backups (a HOST bind mount, so the dumps
# survive `docker compose down -v` which would otherwise destroy the DB volume),
# then prunes dumps older than the retention window. Runs on the postgres:16
# image so pg_dump matches the server version exactly.
#
# This is on-box only. An off-box copy (DigitalOcean Spaces/S3, or a daily
# droplet snapshot) is still strongly recommended for disaster recovery —
# point a sync at $BACKUP_DIR or enable provider snapshots.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"   # daily

mkdir -p "$BACKUP_DIR"
echo "[backup] started; dir=$BACKUP_DIR retention=${RETENTION_DAYS}d interval=${INTERVAL_SECONDS}s"

while true; do
    ts=$(date +%Y%m%d-%H%M%S)
    out="$BACKUP_DIR/anchorpoint-${ts}.sql.gz"
    if PGPASSWORD="$DB_PASS" pg_dump -h db -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
        | gzip > "$out.tmp"; then
        mv "$out.tmp" "$out"
        echo "[backup] wrote $out ($(wc -c < "$out") bytes)"
        # Prune old dumps (only our own files).
        find "$BACKUP_DIR" -name 'anchorpoint-*.sql.gz' -type f -mtime "+$RETENTION_DAYS" -delete
    else
        echo "[backup] pg_dump FAILED at $ts" >&2
        rm -f "$out.tmp"
    fi
    sleep "$INTERVAL_SECONDS"
done
