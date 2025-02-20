FROM python:3.12-alpine AS builder
ARG GUNICORN==23.0.0
ARG PSYCOPG2==2.9.9

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/privacyidea/venv/bin:$PATH"

RUN apk add --no-cache build-base

WORKDIR /privacyidea
COPY . .

RUN python3 -m venv venv && \
    venv/bin/pip install --no-cache-dir --upgrade pip build

RUN venv/bin/python -m build --wheel --outdir dist && \
    venv/bin/pip install --no-cache-dir --find-links=dist dist/*.whl && \
    venv/bin/pip install --no-cache-dir psycopg2-binary==${PSYCOPG2} gunicorn==${GUNICORN}

COPY deploy/docker/healthcheck.py healthcheck.py

# Final Stage: Schlankes Runtime-Image – es werden nur die benötigten Dateien übertragen
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PATH="/privacyidea/venv/bin:/privacyidea/bin:$PATH" \
    PRIVACYIDEA_CONFIGFILE="/privacyidea/etc/pi.cfg" \
    PYTHONPATH=/privacyidea

WORKDIR /privacyidea
VOLUME /privacyidea/etc

RUN apk add --no-cache netcat-openbsd

COPY --from=builder /privacyidea/venv venv
COPY --from=builder /privacyidea/healthcheck.py healthcheck.py

EXPOSE ${PORT}
ENTRYPOINT ["./entrypoint.sh"]
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python /privacyidea/healthcheck.py

