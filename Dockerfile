###############################################################################
# Builder Stage: Code kopieren, Virtualenv erstellen, Wheel bauen und installieren
###############################################################################
FROM cgr.dev/chainguard/wolfi-base AS builder
ARG PYVERSION=3.12
ARG GUNICORN==23.0.0
ARG PSYCOPG2==2.9.9

# Grundlegende Umgebungsvariablen
ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/privacyidea/venv/bin:$PATH"

# Installiere Python, pip, Build-Tools und Git in einem Schritt
RUN apk add --no-cache python-${PYVERSION} py${PYVERSION}-pip build-base

WORKDIR /privacyidea
# Kopiere den gesamten Quellcode (inkl. Submodule – vorher per git checkout und git submodule update sicherstellen)
COPY . .

# Setze Besitz und wechsle zu einem nicht-root Benutzer
RUN chown -R nonroot:nonroot /privacyidea
USER nonroot

# Erstelle ein Virtualenv, upgrade pip und installiere das Build-Tool
RUN python3 -m venv venv && \
    venv/bin/pip install --upgrade pip build

# Baue das privacyIDEA-Paket als Wheel und installiere es sowie weitere Runtime-Abhängigkeiten
RUN venv/bin/python -m build --wheel --outdir dist && \
    venv/bin/pip install --find-links=dist dist/*.whl && \
    venv/bin/pip install psycopg2-binary==${PSYCOPG2} gunicorn==${GUNICORN}

# Kopiere Konfigurationsdateien und Skripte
#COPY deploy/docker/entrypoint.sh venv/bin/entrypoint.sh
#COPY deploy/docker/healthcheck.py venv/bin/healthcheck.py
COPY deploy/docker/entrypoint.sh entrypoint.sh
COPY deploy/docker/healthcheck.py healthcheck.py
COPY deploy/docker/pi.cfg etc/pi.cfg
COPY deploy/docker/logging.cfg etc/logging.cfg

###############################################################################
# Final Stage: Schlankes Runtime-Image – nur benötigte Dateien übernehmen
###############################################################################
FROM cgr.dev/chainguard/wolfi-base
ARG PYVERSION=3.12

ENV PYTHONUNBUFFERED=1 \
    PATH="/privacyidea/venv/bin:/privacyidea/bin:$PATH" \
    PRIVACYIDEA_CONFIGFILE="/privacyidea/etc/pi.cfg" \
    PYTHONPATH=/privacyidea

WORKDIR /privacyidea
VOLUME /privacyidea/etc/persistent

# Installiere den Python-Interpreter (ohne Build-Tools)
RUN apk add --no-cache python-${PYVERSION}

# Übernehme aus der Builder-Stage nur das Virtualenv und den etc-Ordner
COPY --from=builder /privacyidea/venv venv
COPY --from=builder /privacyidea/etc etc
COPY --from=builder /privacyidea/healthcheck.py healthcheck.py
COPY --from=builder /privacyidea/entrypoint.sh entrypoint.sh

# Exponiere den Port (die Umgebungsvariable PORT sollte gesetzt sein)
EXPOSE ${PORT}

# Starte den privacyIDEA-Server über das EntryPoint-Skript
#ENTRYPOINT ["entrypoint.sh"]
ENTRYPOINT ["./entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python /privacyidea/healthcheck.py


