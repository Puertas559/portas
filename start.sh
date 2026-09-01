#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL no está configurada."
  exit 1
fi

python scripts/check_production_env.py
mkdir -p "${DATA_DIR:-/data}"
export FLASK_APP=wsgi.py
flask db upgrade
flask bootstrap-tenant
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers "${WEB_CONCURRENCY:-2}" --threads 4 --timeout 120 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile - wsgi:app
