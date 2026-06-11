#!/bin/sh
# Scheduler loop for the `cron` sidecar service.
#
# Every 60s: deliver any scheduled SMS / phone blasts that are now due.
# Once every ~24h: purge old/unused phone-blast audio files.
#
# Dependency-free on purpose (no system cron / supercronic) — a plain loop is
# enough for a single-instance deployment and keeps the image lean.
set -e

cd /app/anchorpoint

# 1440 minutes = 24h. Start near the threshold so cleanup runs shortly after
# the first boot, then settles into a daily cadence.
CLEANUP_INTERVAL_MIN=1440
minutes_since_cleanup=$CLEANUP_INTERVAL_MIN

echo "[cron] scheduler started"

while true; do
    python manage.py process_communications || echo "[cron] process_communications failed"

    minutes_since_cleanup=$((minutes_since_cleanup + 1))
    if [ "$minutes_since_cleanup" -ge "$CLEANUP_INTERVAL_MIN" ]; then
        python manage.py cleanup_audio || echo "[cron] cleanup_audio failed"
        minutes_since_cleanup=0
    fi

    sleep 60
done
