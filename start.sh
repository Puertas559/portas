#!/bin/sh
set -e

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL no está configurada."
  exit 1
fi

mkdir -p "${DATA_DIR:-/data}"
export FLASK_APP=wsgi.py
flask db upgrade
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers "${WEB_CONCURRENCY:-2}" --threads 4 --timeout 120 wsgi:app
