# 1C Help: app container (Python + p7zip-full + cron для индексации по расписанию).
# Сборка в два этапа: builder ставит зависимости и пакет, runtime — только runtime-зависимости и артефакты.
# Без local-эмбеддингов: docker build --build-arg EMBEDDING_BACKEND=openai_api -t onec-help .
# Кэш зависимостей: BuildKit cache mount для uv (повторные сборки не качают пакеты заново). Требует DOCKER_BUILDKIT=1 (по умолчанию в Docker 23+).
FROM python:3.14-slim AS builder

ARG EMBEDDING_BACKEND=openai_api
ENV UV_SYSTEM_PYTHON=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Установка uv (кэш pip для самой uv)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install uv

# Только pyproject.toml: зависимости и пакет из него (без Flask/requirements.lock)
COPY pyproject.toml README.md ./
COPY src/ src/
# Установка через uv с кэшем: при повторной сборке пакеты берутся из кэша, не из сети
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install .[mcp] \
    && if [ "$EMBEDDING_BACKEND" = "local" ]; then uv pip install .[embed]; fi

# --- Runtime: только slim + утилиты и артефакты из builder ---
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

RUN groupadd -r app --gid=1000 && useradd -r -g app --uid=1000 --create-home app

WORKDIR /app

# Только установленные пакеты и скрипты — без tests, docs, .git, data
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY entrypoint.sh entrypoint-mcp-only.sh crontab ./
RUN chmod +x /app/entrypoint.sh /app/entrypoint-mcp-only.sh \
    && mkdir -p /app/var/log \
    && chown -R app:app /app

ENV PORT=5000
EXPOSE 5000

ENV HELP_PATH=/data
VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "onec_help", "serve", "/data"]
