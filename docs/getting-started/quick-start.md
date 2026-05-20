# Quick Start

Читайте этот файл, если нужно быстро поднять проект, проиндексировать справку и подключить MCP без погружения в детали.

## Что понадобится

- Docker и Docker Compose
- `make`
- каталог с `.hbk`, доступный Docker через `HOST_HELP_SOURCE_BASE`

Если нужна расширенная настройка, локальный `pip`-запуск или troubleshooting, переходите в [../reference/run.md](../reference/run.md).

## 0. Проверьте путь к справке

По умолчанию Docker пытается смонтировать хостовый каталог `/opt/1cv8` внутрь контейнера как `/opt/1cv8`. Если на macOS/Windows Docker Desktop не имеет доступа к этому пути или справка лежит в другом месте, задайте путь хоста в `.env`:

```bash
cp env.example .env
echo 'HOST_HELP_SOURCE_BASE=/path/to/1cv8' >> .env
```

`HELP_SOURCE_BASE` оставьте `/opt/1cv8`, если не меняете контейнерный путь. Если нужно быстро поднять только MCP/Qdrant/Redis без индексации `.hbk`, можно указать пустой доступный каталог:

```bash
mkdir -p data/empty_1cv8
echo 'HOST_HELP_SOURCE_BASE=./data/empty_1cv8' >> .env
```

## 1. Поднимите базовые сервисы

```bash
make up
```

Команда поднимает **qdrant**, **redis** и **mcp**. После этого MCP будет доступен по `http://localhost:8050/mcp`.

Быстрая проверка живости:

```bash
docker ps --filter name=onec-context-mcp
curl -i -H 'Accept: text/event-stream' http://localhost:8050/mcp
```

Для второго вызова нормален ответ `400 Missing session ID`: это означает, что HTTP endpoint поднят и отвечает как MCP streamable HTTP server.

## 2. Поднимите ingest-worker

```bash
make ingest-up
```

Этот шаг нужен для фоновой индексации: в контейнере **ingest-worker** работает **cron** — при старте выполняется **`watchdog --once`**, далее **каждые 10 минут** снова **`watchdog --once`** (hbk, snippets, standards, метаданные по правилам watchdog), а полный **`ingest`** по расписанию **раз в сутки в 3:00**. Обычно **отдельно ничего запускать не нужно**: дождитесь первого прогона watchdog или следующего окна cron.

Если нужен **немедленный полный** прогон ingest (без ожидания 3:00):

```bash
make ingest
```

(команда выполняется **в уже запущенном** ingest-worker.)

## 3. Проверьте, что индекс появился

```bash
make dashboard ARGS='--once'
```

Ожидаемый результат: в статусе видны коллекции и прогресс без ошибок. Сразу после старта ingest-worker полный ingest может ещё не завершиться — дождитесь cron/watchdog или выполните **`make ingest`**, если нужен немедленный полный прогон.

## 4. Полная переинициализация (по желанию)

Очистка коллекций Qdrant и кэша, затем повторная инициализация:

```bash
make reinit ARGS='--force'
```

## 5. Подключите MCP в Cursor

Используйте streamable HTTP server:

- URL: `http://localhost:8050/mcp`
- пример конфига: [../reference/mcp.json.example](../reference/mcp.json.example)

После обновления `.cursor/mcp.json` перезапустите Cursor.

## 6. Минимальная проверка маршрута

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
