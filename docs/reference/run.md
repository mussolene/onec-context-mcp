# Запуск 1C Context MCP

Читайте этот файл, если нужен расширенный запуск: локальный `pip`, Docker Compose details, advanced сценарии и troubleshooting.

Если нужен быстрый старт без деталей, начните с [../getting-started/quick-start.md](../getting-started/quick-start.md).

## Локально

### Вариант A: ingest (рекомендуется)

Одна команда: распаковка `.hbk`, сборка structured `JSONL` из HTML и индексация structured help в Qdrant. Верхний вход проекта: [../../README.md](../../README.md).

```bash
# Qdrant уже запущен (Docker)
docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0

# Ingest из каталога с версиями 1С
HELP_SOURCE_BASE=/opt/1cv8 QDRANT_HOST=localhost PYTHONPATH=src python3 -m onec_help ingest

# MCP (structured JSONL из Qdrant; каталог может быть пустым)
PYTHONPATH=src python3 -m onec_help mcp . --transport streamable-http --host 0.0.0.0 --port 8050
```

### Вариант B: пошагово (unpack → build-index)

1. Установить зависимости: `pip install -e ".[dev]"` (и при необходимости `.[mcp]` для MCP).
2. Распаковать справку:
   - Один архив: `PYTHONPATH=src python3 -m onec_help unpack /path/to/file.hbk -o ./unpacked`
   - Все .hbk из каталога: `PYTHONPATH=src python3 -m onec_help unpack-dir /opt/1cv8 -o ./unpacked -l ru`
4. Запустить Qdrant (Docker): `docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0`
5. Построить structured snapshot и индекс:
   `QDRANT_HOST=localhost QDRANT_PORT=6333 PYTHONPATH=src python3 -m onec_help build-index ./unpacked`
6. MCP локально (stdio или HTTP):
   `PYTHONPATH=src python3 -m onec_help mcp data/help_structured` (stdio) или
   `PYTHONPATH=src python3 -m onec_help mcp data/help_structured --transport streamable-http --host 0.0.0.0 --port 8050`

## Docker Compose

- Данные справки: хостовый каталог **`HOST_HELP_SOURCE_BASE`** монтируется в контейнеры **mcp** и **ingest-worker** как `/opt/1cv8`; внутри контейнера ingest читает **`HELP_SOURCE_BASE`** (по умолчанию `/opt/1cv8`). Подпапки = версии 1С. На Windows при монтировании `C:\Program Files\1cv8` учтите подпапку `bin` — поиск `.hbk` рекурсивный. После ingest канонический runtime-layer лежит в `data/help_structured`.
- **Split (по умолчанию):** `make up` — Qdrant, Redis, **mcp** с **`MCP_MODE=api`** (только API, без фонового ingest/cron). **`make ingest-up`** — добавляет **ingest-worker** (профиль **ingest**): внутри него **cron** — при старте **`watchdog --once`**, далее **`watchdog --once` каждые 10 мин**, полный **`ingest` в 3:00** (см. `crontab` в репозитории). Разовый полный ingest без ожидания cron: **`make ingest`** (exec в **ingest-worker**).
- **Full:** `make up-full` — один контейнер **mcp** с **`MCP_MODE=full`**, фоновый ingest, cron и watchdog в том же образе (см. `entrypoint.sh`).
- Запуск split: `make up` или `docker compose -f docker-compose.base.yml -f docker-compose.yml up -d`. Без `-f` base-файла команда `docker compose up -d` выдаст ошибку.
- Порты по умолчанию: 8050 (MCP, streamable-http), 6333 (Qdrant).
- **Только распаковка:** тот же образ `mcp`, команда `unpack-dir`. Запуск вручную:
  `docker compose -f docker-compose.base.yml -f docker-compose.yml run --rm -v "${HOST_HELP_SOURCE_BASE:-/opt/1cv8}:/input:ro" -v "$(pwd)/unpacked:/output" mcp python -m onec_help unpack-dir /input -o /output -l ru`
- **Логи ingest / watchdog (split):** `make ingest-logs` или `docker compose ... exec ingest-worker tail -f /app/var/log/ingest.log` и `.../watchdog.log`

## Подключение MCP к Cursor

MCP работает **в контейнере** по протоколу **streamable-http** (не stdio). Пример конфигурации лежит в [mcp.json.example](mcp.json.example); рабочий `.cursor/mcp.json` обычно локальный и не коммитится:

- Сервер: `onec-context-mcp`, URL: `http://localhost:8050/mcp`.
- После `make up` (или `docker compose -f docker-compose.base.yml -f docker-compose.yml up -d`) Cursor подключается к контейнеру по этому URL. Перезапустите Cursor после правок конфига.

Базовая проверка после подключения: `get_1c_help_index_status`, затем `get_1c_api_answer` или `search_1c_api`.

## Устранение неполадок

### Пропала база из data/qdrant

Хранилище Qdrant в Docker лежит в **./data/qdrant** (bind-mount в контейнере как `/qdrant/storage`). Папка **data/** в .gitignore — в репозиторий не попадает.

**Обычный перезапуск (`docker compose down` / `up` или `make up`) базу не стирает** — данные на хосте в `./data/qdrant`. База пропадает только если:
- выполнено **`reinit --force`** или **`make reinit ARGS='--force'`** (очистка коллекций и кэша);
- выполнено **`make qdrant-reset`** (удаление каталога data/qdrant);
- каталог **data/qdrant** удалён вручную или при новом клоне не скопирована папка data/.

Если каталог удалён или база пуста (например после `make qdrant-reset`, ручного удаления или нового клона без копирования data/):

1. **Создать каталоги и поднять сервисы:**  
   `make ensure-data && make up`
2. **Запустить ingest-worker:** **`make ingest-up`**. Индексация подхватится **watchdog при старте** и по **cron**; для немедленного полного ingest без ожидания расписания — **`make ingest`**.

Если делали снапшот ранее: `make qdrant-restore` (восстановит из data/backup/), затем при необходимости `make up`.

Рекомендуется периодически делать `make qdrant-backup` — снапшоты сохраняются в data/backup/.

### Где лежит распакованная справка?

По умолчанию **ingest** больше не хранит распакованную справку постоянно. Он использует **временный HTML workspace**, затем строит `data/help_structured/*.jsonl` и удаляет временную распаковку.

Если нужен ручной промежуточный HTML-каталог, используйте:
- `unpack-sync` — структура `version/stem`
- `ingest-from-unpacked` — сборка structured `JSONL` и индекса из такого каталога

Канонический persistent layer проекта теперь `data/help_structured`, а не `data/unpacked`.
`data/unpacked` использовать только как временный или ручной промежуточный каталог.

### Ошибка 500 (UnexpectedResponse) при ingest

Если в списке Failed появляется **UnexpectedResponse: 500 (Internal Server Error)** — ответ вернул **Qdrant** при записи векторов (upsert), а не LM Studio и не этап распаковки.

При 500 индексер автоматически повторяет upsert (пауза 2 с), при повторной ошибке — разбивает батч пополам и пишет половинки отдельно. Если после этого ошибка сохраняется, задача попадает в Failed.

Что проверить:

1. **Логи Qdrant:** `make qdrant-logs` (в Docker) — там может быть причина 500 (память, несовпадение схемы и т.п.).
2. **Размерность векторов:** должна совпадать с коллекцией. По умолчанию 768 (nomic-embed). Задайте **EMBEDDING_DIMENSION** при другой модели (например 1024 для mxbai-embed-large). Если коллекция уже создана с другой размерностью — пересоздайте индекс (`reinit --force`) или укажите правильную размерность до первого ingest.
3. **Размер батча:** при нехватке памяти Qdrant может отдавать 500. Уменьшите **index_batch_size** (например `--index-batch-size 100` или через переменную окружения).
4. **Ресурсы:** при работе в Docker убедитесь, что контейнеру qdrant достаточно памяти.
