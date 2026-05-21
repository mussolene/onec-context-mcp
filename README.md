# 1C Context MCP

[![Test](https://github.com/mussolene/onec-context-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/mussolene/onec-context-mcp/actions/workflows/test.yml)
[![Lint](https://github.com/mussolene/onec-context-mcp/actions/workflows/lint.yml/badge.svg)](https://github.com/mussolene/onec-context-mcp/actions/workflows/lint.yml)
[![Lint Commits](https://github.com/mussolene/onec-context-mcp/actions/workflows/commitlint.yml/badge.svg)](https://github.com/mussolene/onec-context-mcp/actions/workflows/commitlint.yml)
[![Coverage](https://codecov.io/gh/mussolene/onec-context-mcp/graph/badge.svg)](https://codecov.io/gh/mussolene/onec-context-mcp)
[![Release](https://github.com/mussolene/onec-context-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/mussolene/onec-context-mcp/releases)

1C Context MCP распаковывает `.hbk`, строит structured `JSONL` из HTML-справки, индексирует его в Qdrant и поднимает MCP-сервер для поиска по API, snippets, standards, метаданным 1С и агентному контексту.

## Что здесь есть

- `mcp` отдает MCP API по `http://localhost:8050/mcp`
- `qdrant` хранит индексы справки и memory
- `redis` хранит ingest/watchdog cache
- `ingest-worker` выполняет ingest, load-snippets, load-standards и watchdog

Краткое объяснение устройства: [docs/explanation/how-it-works.md](docs/explanation/how-it-works.md).

## Quick Start

Самый короткий путь без локальной индексации `.hbk`:

```bash
make quick-start-prebuilt
```

Команда скачивает готовый публичный Qdrant/BM25 backup, восстанавливает индекс и поднимает MCP на `http://localhost:8050/mcp`. Локальная справка 1С для этого сценария не нужна. Подробности: [docs/getting-started/quick-start.md](docs/getting-started/quick-start.md), [docs/reference/prebuilt-backup.md](docs/reference/prebuilt-backup.md).

Public prebuilt index: [https://cloud.mail.ru/public/NzFn/qLfhyf8zo](https://cloud.mail.ru/public/NzFn/qLfhyf8zo). It is intended for demo/evaluation only; do not publish backups built from private or NDA 1C configurations.

Если нужен свой индекс из локальной `.hbk`-справки:

```bash
cp env.example .env
echo 'HOST_HELP_SOURCE_BASE=/path/to/1cv8' >> .env
make up
make ingest-up
```

После **`make ingest-up`** индексация идёт в **ingest-worker** по cron: `watchdog --once` при старте, затем watchdog каждые 10 минут, полный `ingest` раз в сутки в 3:00. Немедленный полный ingest: **`make ingest`**.

Для метаданных 1С основной route теперь такой:

```bash
# 1. выгрузить XML обработкой tools/1c/MetadataExport.epf в data/metadata_export/<Имя>.xml
# 2. watchdog/metadata-build сами обновят snapshot в этой же папке
make metadata-build
```

Для полной переинициализации с очисткой коллекций и кэша:

```bash
make reinit ARGS='--force'
```

## Подключение MCP

В Cursor и других клиентах используйте streamable HTTP endpoint:

- URL: `http://localhost:8050/mcp`
- пример конфига: [docs/reference/mcp.json.example](docs/reference/mcp.json.example)
- пошаговая проверка: [docs/getting-started/quick-start.md](docs/getting-started/quick-start.md)

## Куда идти дальше

- [docs/README.md](docs/README.md) - карта всей документации
- [docs/getting-started/quick-start.md](docs/getting-started/quick-start.md) - быстрый старт и подключение MCP
- [docs/explanation/how-it-works.md](docs/explanation/how-it-works.md) - как устроен pipeline и сервисы
- [docs/reference/run.md](docs/reference/run.md) - расширенные сценарии запуска и troubleshooting
- [docs/reference/prebuilt-backup.md](docs/reference/prebuilt-backup.md) - готовый публичный Qdrant/BM25 backup для быстрого старта
- [docs/reference/mcp-tools-reference.md](docs/reference/mcp-tools-reference.md) - полный справочник MCP-инструментов
- [docs/reference/metadata-export.md](docs/reference/metadata-export.md) - route для метаданных 1С
- [docs/reference/structured-help-scorecard.md](docs/reference/structured-help-scorecard.md) - метрики качества structured help и stop criteria для extractor
- [docs/reference/1c-testing-guide.md](docs/reference/1c-testing-guide.md) - тестирование Python и 1С-сценариев

## Для контрибьюторов

- [docs/reference/architecture.md](docs/reference/architecture.md) - deployment-режимы и сервисы
- [docs/reference/embedding.md](docs/reference/embedding.md) - embedding pipeline и backends
- [docs/reference/bsl-ls-mcp-setup.md](docs/reference/bsl-ls-mcp-setup.md) - BSL Language Server (CLI / IDE / опционально Docker)
- [docs/cursor-examples/README.md](docs/cursor-examples/README.md) - skill и rules для Cursor
