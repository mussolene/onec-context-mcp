# Документация 1C Context MCP

Эта карта нужна, когда надо быстро понять, куда идти: запустить проект, подключить MCP, проверить runtime route или открыть полный reference.

## Начать здесь

- [getting-started/quick-start.md](getting-started/quick-start.md) - минимальный старт: готовый публичный индекс или свой ingest
- [../README.md](../README.md) - короткий обзор проекта и верхний вход

## Понять систему

- [explanation/how-it-works.md](explanation/how-it-works.md) - что происходит от `.hbk` до MCP-ответов
- [reference/architecture.md](reference/architecture.md) - сервисы, режимы deployment и технические детали

## Справочник

- [reference/run.md](reference/run.md) - расширенные сценарии запуска, локальный режим и troubleshooting
- [reference/prebuilt-backup.md](reference/prebuilt-backup.md) - готовый публичный Qdrant/BM25 backup для быстрого старта
- [reference/mcp-tools-cheatsheet.md](reference/mcp-tools-cheatsheet.md) - короткая шпаргалка по MCP-инструментам
- [reference/mcp-tools-reference.md](reference/mcp-tools-reference.md) - полный reference по параметрам и лимитам
- [reference/metadata-export.md](reference/metadata-export.md) - route для выгрузки и индексации метаданных 1С
- [reference/structured-help-scorecard.md](reference/structured-help-scorecard.md) - метрики качества structured help и stop criteria для extractor
- [reference/mesh-scorecard.md](reference/mesh-scorecard.md) - метрики runtime mesh-поведения и deterministic route
- [getting-started/quick-start.md](getting-started/quick-start.md) + [reference/mesh-scorecard.md](reference/mesh-scorecard.md) - TTM-маршрут: `make quick-start-prebuilt`, подключить MCP, проверить runtime route
- [reference/embedding.md](reference/embedding.md) - embedding pipeline, backends и retry
- [reference/help-formats.md](reference/help-formats.md) - форматы `.hbk`, HTML и structured JSONL
- [reference/search-and-mcp.md](reference/search-and-mcp.md) - рекомендации по качеству поиска и MCP usage
- [reference/bsl-ls-mcp-setup.md](reference/bsl-ls-mcp-setup.md) - BSL Language Server (CLI, IDE, опционально Docker)
- [reference/mcp.json.example](reference/mcp.json.example) - пример Cursor MCP config

## Разработка и тесты

- [reference/1c-testing-guide.md](reference/1c-testing-guide.md) - как тестировать Python и 1С-код
- [codex-examples/README.md](codex-examples/README.md) - Codex-native OACS consumer pack и optional runtime skill
- [cursor-examples/README.md](cursor-examples/README.md) - skill и rules для Cursor
- [snippets/README.md](snippets/README.md) - как загружать реальные сниппеты
- [query-joins-standards.md](query-joins-standards.md) - отдельная заметка по стандартам 1С для запросов
