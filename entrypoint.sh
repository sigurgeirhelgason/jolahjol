#!/bin/sh
set -e

echo "Bíð eftir PostgreSQL..."
until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-jolahjol}" >/dev/null 2>&1; do
    sleep 2
done

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py compilemessages --ignore=.venv
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-30}" \
    --access-logfile -
