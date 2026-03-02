# Changelog — Unpack, Index, Serve Unified

## Unreleased / 2025-03

### Added

- **unpack-sync**: распаковка .hbk в `data/unpacked` с структурой `version/stem/`, `.hbk_info.json`, пропуск без изменений по хэшу.
- **ingest-from-unpacked**: индексация из `data/unpacked` с `path_prefix` в payload (формат `version/platform_lang`).
- **entity_type** в payload индекса: `method`, `property`, `type`, `function`, `constructor`, `event`, `topic` — по section_path/breadcrumb.
- Фильтр `entity_type` в поиске: `search_index`, `search_hybrid`, `search_index_keyword`.
- **INGEST_USE_UNPACKED=1**: ingest выполняет unpack-sync + ingest-from-unpacked вместо temp.
- **Watchdog**: при INGEST_USE_UNPACKED=1 вызывает unpack-sync и ingest-from-unpacked при изменении .hbk.
- **Веб-справка**: breadcrumb, «См. также» (outgoing_links), API `/content/<path>?meta=1` с метаданными.
- **MkDocs-style UI**: сворачиваемые узлы дерева, collapsible секции (Синтаксис, Параметры и т.д.), highlight.js для кода, подсказка «Источник: hbk_slug».
- **get_topic_metadata**: возвращает breadcrumb, outgoing_links, entity_type, hbk_slug из Qdrant.
- **DATA_UNPACKED_DIR**, **HBK_LABELS** — переменные окружения.

### Changed

- `build_index`: параметр `path_prefix` для формирования полного path в payload.
- `serve`: content API возвращает breadcrumb, outgoing_links при `?meta=1`.
- Docker: ingest-worker получает volume `./data/unpacked` и DATA_UNPACKED_DIR.
