#!/bin/sh
set -e

python scripts/check_production_env.py

mkdir -p "${DATA_DIR:-/data}"
export FLASK_APP=wsgi.py
flask db upgrade
flask bootstrap-tenant
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers "${WEB_CONCURRENCY:-2}" --threads "${GUNICORN_THREADS:-4}" --timeout "${GUNICORN_TIMEOUT:-120}" --graceful-timeout 30 --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" --max-requests-jitter 100 --access-logfile - --error-logfile - --capture-output wsgi:app
