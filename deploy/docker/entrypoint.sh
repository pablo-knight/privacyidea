#!/bin/sh
set -xe

PI_PORT="${PI_PORT:-8080}"
PI_LOGLEVEL="${PI_LOGLEVEL:-INFO}"

# Run the app using gunicorn WSGI HTTP server
exec python -m gunicorn -w 4 -b 0.0.0.0:${PI_PORT} "privacyidea.app:create_app(config_name='production')"
