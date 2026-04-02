# Документация 1C Help MCP

Эта карта нужна, когда надо быстро понять, куда идти: запустить проект, разобраться в устройстве или открыть полный reference.

## Начать здесь

- [getting-started/quick-start.md](getting-started/quick-start.md) - минимальный Docker-first старт, индексация и подключение MCP
- [../README.md](../README.md) - короткий обзор проекта и верхний вход

## Понять систему

- [explanation/how-it-works.md](explanation/how-it-works.md) - что происходит от `.hbk` до MCP-ответов
- [reference/architecture.md](reference/architecture.md) - сервисы, режимы deployment и технические детали

## Справочник

- [reference/run.md](reference/run.md) - расширенные сценарии запуска, локальный режим и troubleshooting
- [reference/mcp-tools-cheatsheet.md](reference/mcp-tools-cheatsheet.md) - короткая шпаргалка по MCP-инструментам
- [reference/mcp-tools-reference.md](reference/mcp-tools-reference.md) - полный reference по параметрам и лимитам
- [reference/metadata-export.md](reference/metadata-export.md) - route для выгрузки и индексации метаданных 1С
- [reference/structured-help-scorecard.md](reference/structured-help-scorecard.md) - метрики качества structured help и stop criteria для extractor
- [reference/structured-help-jsonl-first-plan.md](reference/structured-help-jsonl-first-plan.md) - план перехода к JSONL-first help
- [reference/embedding.md](reference/embedding.md) - embedding pipeline, backends и retry
- [reference/help-formats.md](reference/help-formats.md) - форматы `.hbk`, HTML и Markdown
- [reference/search-and-mcp.md](reference/search-and-mcp.md) - рекомендации по качеству поиска и MCP usage
- [reference/bsl-ls-mcp-setup.md](reference/bsl-ls-mcp-setup.md) - подключение внешнего `lsp-bsl-bridge`
- [reference/mcp.json.example](reference/mcp.json.example) - пример Cursor MCP config

## Разработка и тесты

- [reference/1c-testing-guide.md](reference/1c-testing-guide.md) - как тестировать Python и 1С-код
- [cursor-examples/README.md](cursor-examples/README.md) - skill и rules для Cursor
- [snippets/README.md](snippets/README.md) - как загружать реальные сниппеты
- [query-joins-standards.md](query-joins-standards.md) - отдельная заметка по стандартам 1С для запросов

## Архив

- [archive/README.md](archive/README.md) - исторические планы, analyses, reports, audits и verification notes

Архивные документы сохранены для истории решений и повторного анализа, но не входят в основной маршрут onboarding.
