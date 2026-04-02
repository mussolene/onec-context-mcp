# Архитектурный аудит `onec_help`

## Краткий вывод

Репозиторий уже содержит несколько разных подсистем, но код всё ещё лежит в одном плоском пакете `src/onec_help/`.
Это ухудшает навигацию, делает импорты неочевидными и размывает границы ответственности.

На уровне продукта текущее разбиение в целом разумно:

- справка 1С и индекс платформы;
- память/стандарты/сниппеты;
- metadata graph конфигурации;
- runtime orchestration для ingest/watchdog/status;
- delivery interfaces: MCP, CLI, dashboard.

Проблема не в том, что проект умеет "слишком много", а в том, что эти bounded contexts оформлены слабо и до сих пор живут в одном плоском namespace.

## Таблица аудита

| Подсистема | Текущая ответственность | Ключевые модули | Внешние зависимости | Текущие проблемы | Целевая граница | Priority |
|---|---|---|---|---|---|---|
| Help core | Распаковка `.hbk`, TOC, HTML → Markdown | `unpack`, `hbk_container`, `toc_parser`, `html2md`, `categories` | `7z`, `BeautifulSoup` | Лежит рядом с runtime и MCP; нет явного namespace | `onec_help.help_core` | High |
| Search store | Индексация справки, hybrid/BM25, чтение топиков | `indexer`, `sparse_bm25`, `embedding` | `Qdrant` | Слишком большой `indexer.py`; плотная связка с Qdrant и файловой системой | `onec_help.search_store` | High |
| Knowledge | Memory, snippets, standards, metadata graph, task context | `memory`, `loaders/*`, `metadata_graph`, `config_crawler`, `context_builder`, `form_metadata`, `bsl_utils` | `Qdrant`, embedding backend | Смешаны разные виды knowledge; часть маршрутов ещё использует legacy search path | `onec_help.knowledge` | High |
| Runtime | Ingest, watchdog, статусы, redis cache, metrics | `ingest`, `watchdog`, `redis_cache`, `dashboard_data`, `mcp_metrics` | `Redis`, `Qdrant` | Runtime-критичные модули лежат в корне; `redis_cache` слишком мягко деградирует в no-op | `onec_help.runtime` | High |
| Interfaces | MCP server, CLI, dashboard render | `mcp_server`, `cli`, `dashboard_render` | `FastMCP`, terminal UI | Крупные entry modules, слишком много import fan-out | `onec_help.interfaces` | High |
| Shared config/utils | env, HTTP helpers, общие утилиты | `env_config`, `_http`, `_utils` | stdlib | Плоские cross-cutting imports через весь пакет | `onec_help.shared` | Medium |

## Связность хранилищ и кэшей

| Хранилище | Назначение | Правильность | Замечания |
|---|---|---|---|
| `Qdrant / onec_help` | Dense+sparse индекс справки | Хорошо | Правильный primary retrieval store для platform help |
| `Qdrant / onec_help_memory` | Standards/snippets/community memory | Хорошо | Логично отделён от help index |
| `Qdrant / onec_config_metadata` | Metadata graph конфигурации | Хорошо | После exact/semantic split и payload indexes архитектурно корректно |
| `Redis` | ingest status, watchdog state, snippets cache, metrics | Хорошо | Для runtime coordination выбран правильно |
| `Filesystem / data/*` | исходные артефакты, unpacked help, backup, bm25 vocab, pending memory | Условно хорошо | Нужно явно считать файловую систему canonical source для полного контента |
| `JSONL / pending memory` | локальная отложенная очередь | Приемлемо | Это retry-queue, не источник истины |

## Архитектурные проблемы

1. Плоский пакет скрывает реальные границы подсистем.
2. Крупные модули (`mcp_server.py`, `cli.py`, `indexer.py`, `ingest.py`) перегружены.
3. `redis_cache` допускает no-op fallback там, где для runtime нужен fail-fast.
4. Часть нового narrow surface уже внедрена в MCP, но внутренняя оркестрация ещё не везде полностью перешла на него.
5. Интерфейсные модули и runtime orchestration смешаны с domain modules на одном уровне.

## Целевое разбиение пакета

```text
onec_help/
  help_core/
  search_store/
  knowledge/
  runtime/
  interfaces/
  shared/
```

### Предлагаемое наполнение

- `help_core/`
  - `unpack.py`
  - `hbk_container.py`
  - `toc_parser.py`
  - `html2md.py`
  - `categories.py`

- `search_store/`
  - `indexer.py`
  - `embedding.py`
  - `sparse_bm25.py`

- `knowledge/`
  - `memory.py`
  - `metadata_graph.py`
  - `config_crawler.py`
  - `context_builder.py`
  - `form_metadata.py`
  - `bsl_utils.py`
  - `loaders/`
    - `snippets_loader.py`
    - `snippet_classifier.py`
    - `standards_loader.py`
    - `parse_fastcode.py`
    - `parse_helpf.py`
    - `parse_its_v8std.py`

- `runtime/`
  - `ingest.py`
  - `watchdog.py`
  - `redis_cache.py`
  - `dashboard_data.py`
  - `mcp_metrics.py`

- `interfaces/`
  - `mcp_server.py`
  - `cli.py`
  - `dashboard_render.py`

- `shared/`
  - `env_config.py`
  - `_http.py`
  - `_utils.py`

## Рекомендуемая стратегия рефакторинга

1. Сначала ввести подпакеты и переносить low-risk/runtime/interface модули с compatibility wrappers в корне.
2. Затем переносить shared helpers и help core.
3. После этого убрать прямые legacy import paths внутри нового кода.
4. Отдельно ужесточить runtime policy:
   - `ingest-worker` и `watchdog` не должны молча продолжать работу при недоступном Redis.

## Целевой принцип

- Репозиторий остаётся единым.
- Docker/compose остаётся единым.
- MCP остаётся единым продуктом.
- Но код должен быть разделён по ответственности так, чтобы:
  - runtime был отдельно от domain;
  - interfaces были отдельно от orchestration;
  - knowledge был отдельно от help index;
  - shared utilities были явным общим слоем, а не “всё в корне”.
