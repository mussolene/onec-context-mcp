# Quick Start

Читайте этот файл, если нужно быстро поднять проект и подключить MCP без погружения в детали.

## Что понадобится

- Docker и Docker Compose
- `make`
- для prebuilt-сценария локальная `.hbk`-справка не нужна
- для собственного индекса: каталог с `.hbk`, доступный Docker через `HOST_HELP_SOURCE_BASE`

Если нужна расширенная настройка, локальный `pip`-запуск или troubleshooting, переходите в [../reference/run.md](../reference/run.md).

## 1. Быстрый путь с готовым индексом / Fast Path With Prebuilt Index

RU: это основной demo/TTM-путь. Он скачивает публичный Qdrant/BM25 backup,
восстанавливает индекс и поднимает MCP:

```bash
make quick-start-prebuilt
```

EN: this is the primary demo/TTM path. It downloads the public Qdrant/BM25
backup, restores the index and starts MCP.

После завершения MCP доступен по `http://localhost:8050/mcp`. Подробности backup:
[../reference/prebuilt-backup.md](../reference/prebuilt-backup.md).

Быстрая проверка живости:

```bash
curl -i -H 'Accept: text/event-stream' http://localhost:8050/mcp
```

Нормален ответ `400 Missing session ID`: endpoint поднят и отвечает как MCP
streamable HTTP server.

## 2. Если нужен свой индекс из `.hbk`

Задайте путь к локальной справке. `HOST_HELP_SOURCE_BASE` монтируется только в
ingest-worker и ingest/unpack-команды; runtime `mcp` локальную `.hbk`-справку не
монтирует.

```bash
cp env.example .env
echo 'HOST_HELP_SOURCE_BASE=/path/to/1cv8' >> .env
```

`HELP_SOURCE_BASE` оставьте `/opt/1cv8`, если не меняете контейнерный путь.

Поднимите базовые сервисы:

```bash
make up
```

Команда поднимает **qdrant**, **redis** и **mcp**. После этого MCP будет доступен по `http://localhost:8050/mcp`.

Поднимите ingest-worker:

```bash
make ingest-up
```

Этот шаг нужен для фоновой индексации: в контейнере **ingest-worker** работает **cron** — при старте выполняется **`watchdog --once`**, далее **каждые 10 минут** снова **`watchdog --once`** (hbk, snippets, standards, метаданные по правилам watchdog), а полный **`ingest`** по расписанию **раз в сутки в 3:00**. Обычно **отдельно ничего запускать не нужно**: дождитесь первого прогона watchdog или следующего окна cron.

Если нужен **немедленный полный** прогон ingest (без ожидания 3:00):

```bash
make ingest
```

(команда выполняется **в уже запущенном** ingest-worker.)

Проверьте, что индекс появился:

```bash
make dashboard ARGS='--once'
```

Ожидаемый результат: в статусе видны коллекции и прогресс без ошибок. Сразу после старта ingest-worker полный ingest может ещё не завершиться — дождитесь cron/watchdog или выполните **`make ingest`**, если нужен немедленный полный прогон.

Полная переинициализация, если нужно очистить коллекции Qdrant и кэш:

```bash
make reinit ARGS='--force'
```

## 3. Подключите MCP в Cursor

Используйте streamable HTTP server:

- URL: `http://localhost:8050/mcp`
- пример конфига: [../reference/mcp.json.example](../reference/mcp.json.example)

После обновления `.cursor/mcp.json` перезапустите Cursor.

## 4. Минимальная проверка маршрута

После подключения MCP в Cursor:

1. Убедитесь, что сервер `onec-context-mcp` появился в списке MCP.
2. Вызовите `get_1c_help_index_status`.
3. Для быстрой проверки поиска вызовите `get_1c_api_answer` с точным API, например `Формат`, или `search_1c_api` для широкого structured lookup.

## Что читать дальше

- [../explanation/how-it-works.md](../explanation/how-it-works.md) - кратко понять, как устроена система
- [../reference/mesh-scorecard.md](../reference/mesh-scorecard.md) - проверить runtime route и time-to-market сценарии агента
- [../reference/mcp-tools-reference.md](../reference/mcp-tools-reference.md) - полный reference по MCP tools
- [../reference/metadata-export.md](../reference/metadata-export.md) - индексация метаданных 1С
- [../reference/run.md](../reference/run.md) - локальный запуск, compose details и troubleshooting
