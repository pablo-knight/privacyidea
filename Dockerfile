FROM python:3.12-alpine AS builder
ARG GUNICORN==23.0.0
ARG PSYCOPG2==2.9.9

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/privacyidea/venv/bin:$PATH"

RUN apk add --no-cache build-base

WORKDIR /opt/privacyidea
COPY . .

RUN python3 -m venv venv && \
    venv/bin/pip install --no-cache-dir --upgrade pip build

RUN venv/bin/python -m build --wheel --outdir dist && \
    venv/bin/pip install --no-cache-dir --find-links=dist dist/*.whl && \
    venv/bin/pip install --no-cache-dir psycopg2-binary==${PSYCOPG2} gunicorn==${GUNICORN}

COPY deploy/docker/healthcheck.py healthcheck.py
COPY deploy/docker/entrypoint.sh entrypoint.sh

# Final Stage: Schlankes Runtime-Image – nur die benötigten Dateien werden übertragen
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/privacyidea/venv/bin:/opt/privacyidea/bin:$PATH" \
    PRIVACYIDEA_CONFIGFILE="/etc/privacyidea/pi.cfg" \
    PYTHONPATH=/opt/privacyidea

WORKDIR /opt/privacyidea
VOLUME /etc/privacyidea

RUN apk add --no-cache netcat-openbsd

COPY --from=builder /opt/privacyidea/venv venv
COPY --from=builder /opt/privacyidea/healthcheck.py healthcheck.py
COPY --from=builder /opt/privacyidea/entrypoint.sh entrypoint.sh

EXPOSE ${PORT}
ENTRYPOINT ["./entrypoint.sh"]
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python /opt/privacyidea/healthcheck.py

