# Lab 7 proximity search API (FastAPI + Uvicorn)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# Dependencies first so code edits do not reinstall packages.
# The pip cache mount survives between builds but never ships in the image.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=/tmp/requirements.txt \
    pip install --retries 10 -r /tmp/requirements.txt

RUN groupadd --system lab7 && useradd --system --gid lab7 --no-create-home lab7

COPY app ./app
# Default dataset baked in; docker-compose can bind-mount a different CSV over it.
COPY locations.csv /data/locations.csv

ENV LOCATION_DATASET=/data/locations.csv \
    API_PORT=8100 \
    UVICORN_WORKERS=2 \
    UVICORN_LIMIT_CONCURRENCY=64 \
    UVICORN_BACKLOG=2048

USER lab7
EXPOSE 8100

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('API_PORT', '8100') + '/health', timeout=2)"]

# exec makes Uvicorn PID 1 so it receives SIGTERM from `docker stop`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$API_PORT\" --workers \"$UVICORN_WORKERS\" --limit-concurrency \"$UVICORN_LIMIT_CONCURRENCY\" --backlog \"$UVICORN_BACKLOG\" --timeout-keep-alive 5 --proxy-headers --forwarded-allow-ips '*'"]
