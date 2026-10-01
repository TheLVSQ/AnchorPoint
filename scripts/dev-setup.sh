#!/usr/bin/env bash
# Local dev/test environment for AnchorPoint (macOS + OrbStack, or any Docker).
#
#   scripts/dev-setup.sh          # idempotent: db up, venv synced, .env present
#   scripts/dev-setup.sh test     # ...then run the full Django + agent test suites
#
# What it sets up:
#   - Postgres 16 in a container "anchorpoint-dev-db" on localhost:5433
#     (5433, not 5432, so it never collides with another project's Postgres)
#   - .venv/ at the repo root on Python 3.12 (matches docker/Dockerfile)
#   - anchorpoint/.env with DEBUG=True, a random SECRET_KEY and the DB_* settings
#     (only written if missing — edit it freely afterwards)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_CONTAINER="anchorpoint-dev-db"
DB_VOLUME="anchorpoint_dev_pg"
DB_PORT=5433

# 1. Docker daemon (start OrbStack if that's what's installed)
if ! docker info >/dev/null 2>&1; then
  if command -v orb >/dev/null 2>&1; then
    echo "Starting OrbStack..."
    orb start >/dev/null 2>&1 || true
  fi
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || { echo "Docker isn't running. Start OrbStack/Docker and re-run."; exit 1; }
fi

# 2. Postgres 16
if docker ps -a --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  docker start "$DB_CONTAINER" >/dev/null
else
  docker run -d --name "$DB_CONTAINER" \
    -e POSTGRES_DB=anchorpoint -e POSTGRES_USER=anchorpoint -e POSTGRES_PASSWORD=anchorpoint \
    -p "127.0.0.1:${DB_PORT}:5432" -v "${DB_VOLUME}:/var/lib/postgresql/data" \
    postgres:16-alpine >/dev/null
fi
for _ in $(seq 1 30); do
  docker exec "$DB_CONTAINER" pg_isready -U anchorpoint -q 2>/dev/null && break; sleep 1
done
echo "Postgres: localhost:${DB_PORT} (container ${DB_CONTAINER})"

# 3. Python 3.12 venv
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  [ -x .venv/bin/python ] || uv venv --python 3.12 .venv -q
  uv pip install --python .venv/bin/python -q -r docker/requirements.txt
else
  [ -x .venv/bin/python ] || python3.12 -m venv .venv
  .venv/bin/pip install -q -r docker/requirements.txt
fi
echo "Python: $(.venv/bin/python --version) in .venv/"

# 4. anchorpoint/.env (settings.py loads it)
ENV_FILE="$ROOT/anchorpoint/.env"
if [ ! -f "$ENV_FILE" ]; then
  SECRET=$(.venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())")
  cat > "$ENV_FILE" <<EOF
SECRET_KEY=${SECRET}
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=anchorpoint
DB_USER=anchorpoint
DB_PASS=anchorpoint
DB_HOST=127.0.0.1
DB_PORT=${DB_PORT}
EOF
  echo "Wrote anchorpoint/.env"
fi

if [ "${1:-}" = "test" ]; then
  cd "$ROOT/anchorpoint"
  ../.venv/bin/python manage.py test --noinput --parallel auto
  cd "$ROOT/agent"
  ../.venv/bin/python -m unittest test_agent
else
  cat <<EOF

Ready. Common commands (from the repo root):
  scripts/dev-setup.sh test                                   # full test suite
  cd anchorpoint && ../.venv/bin/python manage.py migrate      # set up the dev DB
  cd anchorpoint && ../.venv/bin/python manage.py create_admin --username admin --email you@example.com
  cd anchorpoint && ../.venv/bin/python manage.py runserver
EOF
fi
