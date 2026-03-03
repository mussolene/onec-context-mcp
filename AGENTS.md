# AGENTS.md — 1C Help MCP

## Назначение проекта

- Справка 1С: распаковка .hbk (7z), конвертация HTML → Markdown, индексация в Qdrant, MCP-сервер для поиска/чтения справки.
- Конфигурация через переменные окружения. БД — Qdrant в docker-compose.
- Дальнейшие этапы: один–два MCP по кодовой базе и метаданным 1С (задел в README).

## Команды и сценарии

- **Единая точка входа:** **ingest** — загрузка/обновление индекса (поиск .hbk в HELP_SOURCE_BASE, распаковка, Markdown, Qdrant). **reinit --force** — полная перезагрузка: очистка коллекций и кэша, затем init (ingest + load-snippets + load-standards). Без миграций и отдельных шагов unpacked.
- **Локально:** `python -m onec_help ingest|reinit|init|index-status|mcp|unpack|build-index|load-snippets|load-standards|watchdog ...`
- **init** — ingest + load-snippets + load-standards (HELP_SOURCE_BASE, SNIPPETS_DIR, STANDARDS_REPOS). Не стирает данные.
- **reinit --force** — очистка коллекций и cache, затем init. Для перезапуска «с нуля».
- **Docker:** `docker-compose up` (qdrant + mcp). Индексация: `make ingest`. Полная перезагрузка: `make reinit ARGS='--force'`. Cron в 3:00 — ingest; при WATCHDOG_ENABLED=1 — watchdog в фоне. BSL LS — `make bsl-start`.
- **read-hbk-container** — чтение .hbk как бинарного контейнера (alkoleft/hbk-viewer): сущности, извлечение в каталог, TOC в JSON (вспомогательная команда).
- **Сниппеты:** ./data/snippets, parse-fastcode/parse-helpf пишут туда, `load-snippets` загружает. `make snippets` — оба сайта; `make parse-helpf` — только FAQ.
- **Стандарты:** `make load-standards` — v8-code-style и v8std (STANDARDS_REPOS).

## Ingest: переиндексация при перезапуске

Если файлы переиндексируются при каждом перезапуске:

1. **INGEST_CACHE_FILE** — в Docker: `/app/var/ingest_cache/ingest_cache.db` (→ ./data/ingest_cache).
2. **Ошибка чтения кэша** — при `[ingest] WARN: ingest cache read failed` проверьте права, существование файла, место на диске. В логе будет подсказка.
3. **Распаковка по умолчанию** — ingest пишет в **data/unpacked** (DATA_UNPACKED_DIR) структуру **version/stem** (run_unpack_sync), затем run_ingest_from_unpacked индексирует из неё. Команда **ingest-from-unpacked** ожидает именно эту структуру; вывод **unpack-dir** (version/lang/name) с ней не совместим. INGEST_USE_TEMP=1 — временная папка с удалением после индексации.
4. **Watchdog** — state в INGEST_CACHE (watchdog_hbk_cache.json); при рестарте неизменённые .hbk пропускаются по кэшу.
5. **reinit --force** — стирает коллекции и кэш, затем init; полная переиндексация ожидаема.

## Embedding и индексация

- **Точки интеграции:** indexer (справка), memory.upsert_curated_snippets (snippets, community_help, standards), memory.process_pending, memory._write_long_or_pending (real-time). Все batch-операции используют `get_embedding_batch`; только real-time события — `get_embedding`.
- **Единая логика:** sanitize, truncation 2000 символов, retry при len(vectors)!=len(items), 429+Retry-After, EMBEDDING_MAX_CONCURRENT (семафор), retry с меньшим батчем перед fallback. См. `docs/embedding.md`.
- **Бэкенды:** local, openai_api, deterministic (384 dim без модели), none (плейсхолдер).

## Структура кода

- `src/onec_help/`: пакет (unpack, categories, html2md, tree, indexer, memory, parse_fastcode, parse_helpf, snippet_classifier, standards_loader, watchdog, mcp_server, cli, hbk_container, toc_parser).
- `unpack` — 7z, zipfile, ZIP from offset, unzip, scan local headers, **HBK binary container** (источник: alkoleft/hbk-viewer); при контейнере пишет `.toc.json`; `unpack-diag` — диагностика при ошибке; `hbk_container` — чтение бинарного .hbk (FileStorage, PackBlock, Book); `toc_parser` — разбор текста PackBlock TOC в плоский список (path, title_ru/en, breadcrumb, entity_type); `categories` — парсинг `__categories__` и дерево TOC; `html2md` — HTML → Markdown; `tree` — дерево (build_tree_for_web и др.); `indexer` — Qdrant, при наличии `.toc.json` в source_dir подмешивает title/breadcrumb/section_path в payload; `memory` — тройная память; `watchdog` — мониторинг .hbk и pending embeddings; `mcp_server` — FastMCP (search_1c_help, get_1c_help_topic, get_1c_function_info, save_1c_snippet, get_1c_help_related, compare_1c_help, trigger_reindex и др.). Payload точек при TOC содержит `breadcrumb`, `entity_type`.
- Тесты в `tests/`, покрытие ≥70% (pytest-cov, `--cov-fail-under=70`).
- Фикстуры — минимальный срез справки в `tests/fixtures/help_sample/`.

## MCP и конфиг Cursor

- MCP работает **в контейнере** по протоколу **streamable-http** (порт 8050). Рабочий конфиг: **`.cursor/mcp.json`** с полем `url: "http://localhost:8050/mcp"` (без command/stdio). Пример — `docs/mcp.json.example`.
- **Skill и Rules:** примеры для индексации и синхронизации — `docs/cursor-examples/`. Папка `.cursor/` исключена из git; при настройке Cursor скопируйте содержимое `docs/cursor-examples/` в `.cursor/skills/` и `.cursor/rules/`. При доработке MCP или workflow — обновляйте `docs/cursor-examples/` как зависимость.
- **Рекомендуемый порядок вызовов:**
  1. Ответ с кодом — `get_1c_code_answer` (при необходимости `code_only=True`).
  2. Недостаток деталей — `get_1c_help_topic(topic_path)` (параметр `topic_path`, не `path`).
  3. Точные имена API — `search_1c_help_keyword` с полным именем (в т.ч. `Тип.Метод`).
  4. Несколько совпадений в `get_1c_function_info` — указывать `choose_index`.
  5. После генерации кода — `save_1c_snippet` для сохранения полезных примеров.
- **Типовые ловушки:** ПрочитатьJSON возвращает Структуру по умолчанию — для Соответствия указывать `ПрочитатьВСоответствие=Истина`. HTTPСоединение.Получить — только на сервере. Имена методов вида `Тип.Метод` передавать целиком в `search_1c_help_keyword`.
- **При добавлении новых MCP-сервисов** их нужно прописать в `.cursor/mcp.json`: для удалённого сервера — запись в `mcpServers` с полем `url`; для локального — `command`, `args`, при необходимости `env`. После изменений конфига Cursor перезапускают.

## Безопасность

- MCP по HTTP не имеет аутентификации; рассчитан **только** на доверенную сеть (localhost/VPN). При экспозиции в интернет — обязателен обратный прокси с аутентификацией.

## Конфиденциальность и NDA

- **Embedding API:** текст справки 1С и поисковые запросы отправляются на внешний сервис (LM Studio, OpenAI и т.п.). При работе с конфиденциальными данными или NDA используйте on-prem сервис эмбеддингов (EMBEDDING_API_URL на внутренний хост).
- **Memory (MEMORY_ENABLED=1):** история сессий (topic_path, save_snippet, exchange) хранится в JSONL и Qdrant. Учитывайте политику хранения и доступ к этим данным.
- **save_1c_snippet:** сохранённый код пишется в memory. При SAVE_SNIPPET_TO_FILES=1 — также в SNIPPETS_DIR. При конфиденциальном коде настройте SNIPPETS_DIR и MEMORY_BASE_PATH в защищённое место.
- **Логи:** в production (PRODUCTION=1) в ответах API и логах не раскрываются полные пути и текст исключений.

## Правила

- Язык кода и комментариев — по контексту (рус/англ). Пути и конфигурация — только через аргументы и env, без хардкода.
- **Сохранять рабочий код 1С:** при выдаче исполняемого примера 1С, которого нет в базовых сниппетах, вызывать `save_1c_snippet` с кодом и описанием — это улучшит `get_1c_code_answer` в следующих сессиях.
- Не трогать план в `.cursor/plans/`. При доработках сохранять совместимость с docker-compose и Qdrant. При изменении MCP или workflow — проверить и обновить `docs/cursor-examples/` (skill, rules).
- Использовать subagent'ы при необходимости для объёмных задач.

### Работа с 1С-кодом

- **Два MCP:** при генерации кода — 1c-help (`get_1c_code_answer`, `search_1c_help_keyword`); при проверке/рефакторинге — lsp-bsl-bridge (`document_diagnostics`, `code_actions`). Если 1c-help недоступен (нет индекса) — опереться на BSL LS и memory.
- **После правок 1С:** вызывать `document_diagnostics` для проверки ошибок, предупреждений и соответствия стандартам BSL LS. URI для Docker: `file:///projects/<path>/Module.bsl` (volume `.:/projects`).
- **Стандарты:** учитывать правила 1С (BSL LS diagnostics + v8-code-style и v8std из `load-standards`).

## Workflow разработки 1С с BSL LS

Циклы с проверками; при ошибках — возврат к шагу исправления.

1. **Индексация.** `make up` или `docker compose up -d`. BSL LS: `make bsl-start` (отдельно), volume `.:/projects`. Дождаться индексации (`lsp_status`).
2. **Ориентирование.** `project_analysis` — поиск символов/файлов; `symbol_explore` — детали по символу; `call_graph` — граф вызовов перед рефакторингом (обязательно перед правками).

### Цикл «Написание кода»

`get_1c_code_answer` / `search_1c_help_keyword` → реализация → `document_diagnostics` → при ERROR/WARNING: исправить и повторить diagnostics до чистоты → `save_1c_snippet` (если переиспользуемо) → опционально unit-тест 1С (xUnitFor1C, Vanessa-Automation).

### Цикл «Рефакторинг»

`call_graph` + `project_analysis` → `document_diagnostics` (базовое состояние) → правка одного файла → `document_diagnostics` → при ERROR: исправить и повторить → после batch: `did_change_watched_files` → следующий файл.

### Слой тестирования

- **BSL LS:** `document_diagnostics` — статический анализ (не runtime). Вызывать после каждой правки; цикл до чистоты.
- **Python (onec_help):** `PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70`; `ruff check src tests && ruff format --check src tests`. При падении покрытия — добавить тесты.
- **1C runtime:** xUnitFor1C (unit), Vanessa-Automation (BDD), CoverageBSL. При новой логике — предлагать/создавать тесты. Если есть `Tests/` или `features/` — считать тесты частью workflow.
