FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production HOST=0.0.0.0 PORT=8000 \
    RUNTIME_DIR=/var/lib/sentinelops WATCHER_ENABLED=false LOG_JSON=true
WORKDIR /opt/sentinelops
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sentinelops \
    && useradd --uid 10001 --gid 10001 --no-create-home sentinelops \
    && mkdir -p /var/lib/sentinelops/workspaces \
    && chown -R 10001:10001 /var/lib/sentinelops
COPY requirements-production.lock ./
RUN python -m pip install --no-cache-dir -r requirements-production.lock
COPY app ./app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/ready',timeout=3)"
CMD ["python", "-m", "app.serve"]
