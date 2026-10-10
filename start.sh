#!/usr/bin/env bash
set -e
# One shared, private token per container; no manual environment setup needed.
export WA_INTERNAL_TOKEN="${WA_INTERNAL_TOKEN:-$(python -c 'import secrets; print(secrets.token_hex(32))')}"
node whatsapp-bridge/server.js &
exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 180 wsgi:app
