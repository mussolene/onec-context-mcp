# Запуск 1C Help

Читайте этот файл, если нужен расширенный запуск: локальный `pip`, Docker Compose details, advanced сценарии и troubleshooting.

Если нужен быстрый старт без деталей, начните с [../getting-started/quick-start.md](../getting-started/quick-start.md).

## Локально

### Вариант A: ingest (рекомендуется)

Одна команда: распаковка `.hbk`, сборка structured `JSONL` из HTML и индексация structured help в Qdrant. Верхний вход проекта: [../../README.md](../../README.md).

```bash
# Qdrant уже запущен (Docker)
docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0

# Ingest из каталога с версиями 1С
HELP_SOURCE_BASE=/opt/1cv8 QDRANT_HOST=localhost python -m onec_help ingest

# MCP (structured JSONL из Qdrant; каталог может быть пустым)
python -m onec_help mcp . --transport streamable-http --host 0.0.0.0 --port 8050
```

### Вариант B: пошагово (unpack → build-index)

1. Установить зависимости: `pip install -e ".[dev]"` (и при необходимости `.[mcp]` для MCP).
2. Распаковать справку:
   - Один архив: `python -m onec_help unpack /path/to/file.hbk -o ./unpacked`
   - Все .hbk из каталога: `python -m onec_help unpack-dir /opt/1cv8 -o ./unpacked -l ru`
4. Запустить Qdrant (Docker): `docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0`
5. Построить structured snapshot и индекс:  
   `QDRANT_HOST=localhost QDRANT_PORT=6333 python -m onec_help build-index ./unpacked`
6. MCP локально (stdio или HTTP):  
   `python -m onec_help mcp data/help_structured` (stdio) или  
   `python -m onec_help mcp data/help_structured --transport streamable-http --host 0.0.0.0 --port 8050`

## Docker Compose

- Данные справки: монтируется `/opt/1cv8` в контейнер mcp, подпапки = версии 1С. Индексация вручную: `docker compose exec mcp python -m onec_help ingest`; по расписанию в mcp запущен cron (раз в сутки в 3:00). На Windows при монтировании `C:\Program Files\1cv8` учтите подпапку `bin` — поиск `.hbk` рекурсивный. После ingest канонический runtime-layer лежит в `data/help_structured`.
- Запуск: `make up` или `docker compose -f docker-compose.base.yml -f docker-compose.yml up -d` — поднимает Qdrant и MCP-сервер (mcp; в нём же cron для индексации). Без `-f` base-файла команда `docker compose up -d` выдаст ошибку.
- Порты по умолчанию: 8050 (MCP, streamable-http), 6333 (Qdrant).
- **Только распаковка:** тот же образ `mcp`, команда `unpack-dir`. Запуск вручную:  
  `docker compose run --rm -v /opt/1cv8:/input:ro -v $(pwd)/unpacked:/output mcp python -m onec_help unpack-dir /input -o /output -l ru`
- **Логи ingest:** `docker compose exec mcp tail -f /app/var/log/ingest.log`

## Подключение MCP к Cursor

MCP работает **в контейнере** по протоколу **streamable-http** (не stdio). В проекте уже есть **`.cursor/mcp.json`**:

- Сервер: `1c-help`, URL: `http://localhost:8050/mcp`.
- После `make up` (или `docker compose -f docker-compose.base.yml -f docker-compose.yml up -d`) Cursor подключается к контейнеру по этому URL. Перезапустите Cursor после правок конфига.

Инструменты: `get_1c_api_answer`, `search_1c_api`, `get_1c_api_object`.

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
2. **Запустить ingest-worker и заново проиндексировать:**  
   `make ingest-up` затем `make ingest` (или дождаться watchdog)

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
