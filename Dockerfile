# 1C Help: app container (Python + p7zip-full + cron для индексации по расписанию).
# Зависимости для эмбеддингов ставятся только при EMBEDDING_BACKEND=local. Для openai_api, none или deterministic:
#   docker build --build-arg EMBEDDING_BACKEND=none -t onec-help .
FROM python:3.14-slim

ARG EMBEDDING_BACKEND=openai_api

# Базовый slim не содержит: 7z, unzip, cron, gosu
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    unzip \
    cron \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for app and cron jobs
RUN groupadd -r app --gid=1000 && useradd -r -g app --uid=1000 --create-home app

WORKDIR /app

COPY requirements.lock .
# numpy 2.4+ и qdrant-client 1.17+ имеют готовые wheel под Python 3.14 (manylinux), без сборки из исходников
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml .
COPY src/ src/
COPY entrypoint.sh entrypoint-mcp-only.sh crontab ./
RUN chmod +x /app/entrypoint.sh /app/entrypoint-mcp-only.sh \
    && pip install --no-cache-dir -e ".[mcp]" \
    && if [ "$EMBEDDING_BACKEND" = "local" ]; then pip install --no-cache-dir -e ".[embed]"; fi \
    && mkdir -p /app/var/log \
    && chown -R app:app /app

ENV PORT=5000
EXPOSE 5000

# Default: run MCP over stdio; override with CMD serve /data or custom
ENV HELP_PATH=/data
VOLUME ["/data"]

# Healthcheck removed from image — set per-service in docker-compose (Flask :5000 vs MCP :8050)

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "onec_help", "serve", "/data"]
