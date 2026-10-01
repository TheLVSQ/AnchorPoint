#!/bin/sh
# Drop root before running anything. Used as the entrypoint wrapper for both the
# web and cron services: `as-app.sh <command...>`.
#
# The container starts as root only so it can hand the media volume to the
# unprivileged `app` user. Existing volumes were written by root before the
# image went non-root, and anything created later by a root `docker compose
# exec` (e.g. a management command) would otherwise be unwritable for the app.
set -e

if [ "$(id -u)" = "0" ]; then
    find /app/anchorpoint/media ! -user app -exec chown app:app {} + 2>/dev/null || true
    exec setpriv --reuid=app --regid=app --init-groups -- "$@"
fi

exec "$@"
