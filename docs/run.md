# Запуск 1C Help

## Локально

### Вариант A: ingest (рекомендуется)

Одна команда: распаковка .hbk, конвертация в Markdown, индексация в Qdrant. Подробнее см. [README.md](../README.md).

```bash
# Qdrant уже запущен (Docker)
docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0

# Ingest из каталога с версиями 1С
HELP_SOURCE_BASE=/opt/1cv8 QDRANT_HOST=localhost python -m onec_help ingest

# MCP (топики из Qdrant; каталог может быть пустым)
python -m onec_help mcp . --transport streamable-http --host 0.0.0.0 --port 8050
```

### Вариант B: пошагово (unpack → build-docs → build-index)

1. Установить зависимости: `pip install -e ".[dev]"` (и при необходимости `.[mcp]` для MCP).
2. Распаковать справку:
   - Один архив: `python -m onec_help unpack /path/to/file.hbk -o ./unpacked`
   - Все .hbk из каталога: `python -m onec_help unpack-dir /opt/1cv8 -o ./unpacked -l ru`
3. Сгенерировать Markdown:  
   `python -m onec_help build-docs ./unpacked -o ./docs_md`
4. Запустить Qdrant (Docker): `docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0`
5. Построить индекс:  
   `QDRANT_HOST=localhost QDRANT_PORT=6333 python -m onec_help build-index ./docs_md`
6. MCP локально (stdio или HTTP):  
   `python -m onec_help mcp ./unpacked` (stdio) или  
   `python -m onec_help mcp ./unpacked --transport streamable-http --host 0.0.0.0 --port 8050`

## Docker Compose

- Данные справки: монтируется `/opt/1cv8` в контейнер mcp, подпапки = версии 1С. Индексация вручную: `docker compose exec mcp python -m onec_help ingest`; по расписанию в mcp запущен cron (раз в сутки в 3:00). На Windows при монтировании `C:\Program Files\1cv8` учтите подпапку `bin` — поиск .hbk рекурсивный.
- `docker compose up -d` — поднимает Qdrant и MCP-сервер (mcp; в нём же cron для индексации).
- Порты: 8050 (MCP, streamable-http), 6333 (Qdrant).
- **Только распаковка:** тот же образ `mcp`, команда `unpack-dir`. Запуск вручную:  
  `docker compose run --rm -v /opt/1cv8:/input:ro -v $(pwd)/unpacked:/output mcp python -m onec_help unpack-dir /input -o /output -l ru`
- **Логи ingest:** `docker compose exec mcp tail -f /app/var/log/ingest.log`

## Подключение MCP к Cursor

MCP работает **в контейнере** по протоколу **streamable-http** (не stdio). В проекте уже есть **`.cursor/mcp.json`**:

- Сервер: `1c-help`, URL: `http://localhost:8050/mcp`.
- После `docker compose up -d` Cursor подключается к контейнеру по этому URL. Перезапустите Cursor после правок конфига.

Инструменты: `search_1c_help`, `get_1c_help_topic`, `get_1c_function_info`.

## Устранение неполадок

### Пропала база из data/qdrant

Хранилище Qdrant в Docker лежит в **./data/qdrant** (bind-mount в контейнере как `/qdrant/storage`). Папка **data/** в .gitignore — в репозиторий не попадает.

Если каталог удалён (например после `make qdrant-reset`, ручного удаления или нового клона без копирования data/):

1. **Создать каталоги и поднять сервисы:**  
   `make ensure-data && make up`
2. **Заново проиндексировать справку:**  
   `make ingest`

Если делали снапшот ранее: `make qdrant-restore` (восстановит из data/backup/), затем при необходимости `make up`.

Рекомендуется периодически делать `make qdrant-backup` — снапшоты сохраняются в data/backup/.

### Где лежит распакованная справка?

По умолчанию **ingest** распаковывает все .hbk в **одну папку** — **data/unpacked** (или `DATA_UNPACKED_DIR`). Там создаётся структура **`version/stem/`** (например `8.3.27.1719/1cv8_ru/`) — один уровень под версией, без языка в пути. Эту структуру создаёт **run_unpack_sync** (внутри ingest). После распаковки идёт индексация из неё (**run_ingest_from_unpacked**). Файлы не удаляются.

**Важно:** команда **ingest-from-unpacked** (и внутренний вызов при обычном ingest) ожидает каталоги в формате **version/stem**, т.е. вывод **run_unpack_sync** или основного **ingest**. Команда **unpack-dir** (run_unpack_only) пишет в структуру **version/lang/safe_name** (язык в пути) — такая структура **не совместима** с ingest-from-unpacked; для индексации из уже распакованного используйте каталог, полученный через ingest или unpack-sync.

Если нужен старый режим (временная папка с удалением после индексации), задайте **INGEST_USE_TEMP=1**.

### Ошибка 500 (UnexpectedResponse) при ingest

Если в списке Failed появляется **UnexpectedResponse: 500 (Internal Server Error)** — ответ вернул **Qdrant** при записи векторов (upsert), а не LM Studio и не этап распаковки.

При 500 индексер автоматически повторяет upsert (пауза 2 с), при повторной ошибке — разбивает батч пополам и пишет половинки отдельно. Если после этого ошибка сохраняется, задача попадает в Failed.

Что проверить:

1. **Логи Qdrant:** `make qdrant-logs` (в Docker) — там может быть причина 500 (память, несовпадение схемы и т.п.).
2. **Размерность векторов:** должна совпадать с коллекцией. Задайте **EMBEDDING_DIMENSION** в соответствии с моделью в LM Studio (например 768 для nomic-embed, 1024 для mxbai-embed-large). Если коллекция уже создана с другой размерностью — пересоздайте индекс (`reinit --force`) или укажите правильную размерность до первого ingest.
3. **Размер батча:** при нехватке памяти Qdrant может отдавать 500. Уменьшите **index_batch_size** (например `--index-batch-size 100` или через переменную окружения).
4. **Ресурсы:** при работе в Docker убедитесь, что контейнеру qdrant достаточно памяти.
