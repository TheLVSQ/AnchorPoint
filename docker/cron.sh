#!/bin/sh
# Scheduler loop for the `cron` sidecar service.
#
# Every 60s: deliver any scheduled SMS / phone blasts that are now due, and
# rebuild the church website if the public events feed changed (debounced).
# Once every ~24h: purge old/unused phone-blast audio files and old label images,
# then run the system health check (emails Maintenance Alerts recipients).
# Nightly at 07:00 UTC (2am EST / 3am EDT, before the Tuesday 07:30 reboot
# window): family/person hygiene → the admin "Data cleanup" queue.
#
# Dependency-free on purpose (no system cron / supercronic) — a plain loop is
# enough for a single-instance deployment and keeps the image lean.
set -e

cd /app/anchorpoint

# 1440 minutes = 24h. Start near the threshold so cleanup runs shortly after
# the first boot, then settles into a daily cadence.
CLEANUP_INTERVAL_MIN=1440
minutes_since_cleanup=$CLEANUP_INTERVAL_MIN
last_hygiene_day=""

echo "[cron] scheduler started"

while true; do
    python manage.py process_communications || echo "[cron] process_communications failed"
    python manage.py trigger_site_rebuild || echo "[cron] trigger_site_rebuild failed"

    minutes_since_cleanup=$((minutes_since_cleanup + 1))
    if [ "$minutes_since_cleanup" -ge "$CLEANUP_INTERVAL_MIN" ]; then
        python manage.py cleanup_audio || echo "[cron] cleanup_audio failed"
        python manage.py purge_print_images || echo "[cron] purge_print_images failed"
        python manage.py system_health || echo "[cron] system_health failed"
        minutes_since_cleanup=0
    fi

    # Once per UTC day during the 07:00 hour (idempotent, so a re-run after a
    # restart in that hour is harmless).
    if [ "$(date -u +%H)" = "07" ] && [ "$last_hygiene_day" != "$(date -u +%F)" ]; then
        python manage.py family_hygiene || echo "[cron] family_hygiene failed"
        last_hygiene_day=$(date -u +%F)
    fi

    sleep 60
done
