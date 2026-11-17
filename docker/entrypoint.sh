#!/bin/sh
set -e

python manage.py migrate --noinput

# First run of a demo: fill an empty database with synthetic sample data.
if [ "${DEMO_DATA:-0}" = "1" ]; then
  python manage.py bootstrap_demo --raw /app/data/raw
fi

exec "$@"
