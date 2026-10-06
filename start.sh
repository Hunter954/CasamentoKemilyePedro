#!/usr/bin/env bash
set -e
node whatsapp-bridge/server.js &
exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 180 wsgi:app
