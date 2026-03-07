# AGENTS.md — 1C Help MCP

## Назначение проекта

- Справка 1С: распаковка .hbk (7z), конвертация HTML → Markdown, индексация в Qdrant, MCP-сервер для поиска/чтения справки.
- Конфигурация через переменные окружения. БД — Qdrant в docker-compose.
- Дальнейшие этапы: один–два MCP по кодовой базе и метаданным 1С (задел в README).

## Команды и сценарии

- **Единая точка входа:** **ingest** — загрузка/обновление индекса (поиск .hbk в HELP_SOURCE_BASE, распаковка, Markdown, Qdrant). **reinit --force** — полная перезагрузка: очистка коллекций и кэша, затем init (ingest + load-snippets + load-standards). Без миграций и отдельных шагов unpacked.
- **Локально:** `python -m onec_help ingest|reinit|init|dashboard|mcp|unpack|build-index|load-snippets|load-standards|watchdog ...`
- **init** — ingest, load-snippets и load-standards запускаются **параллельно** (асинхронно). Не стирает данные.
- **reinit --force** — очистка коллекций и cache, затем init. Для перезапуска «с нуля».
- **Docker:** по умолчанию `make up` — только **qdrant** и **mcp**. Для индексации и watchdog: **`make ingest-up`** (поднимает ingest-worker с watchdog). Индексация вручную: `make ingest` (требует запущенный ingest-worker). Полная перезагрузка: `make reinit ARGS='--force'`. Cron в 3:00 — в full-режиме. BSL LS — `make bsl-start`.
- **dashboard** — дашборд (Tasks, Errors, Qdrant, версии 1С): `--once` один кадр, иначе Live с `--interval`.
- **read-hbk-container** — чтение .hbk как бинарного контейнера (alkoleft/hbk-viewer): сущности, извлечение в каталог, TOC в JSON (вспомогательная команда).
- **Сниппеты:** ./data/snippets, parse-fastcode/parse-helpf пишут туда, `load-snippets` загружает. `make snippets` — оба сайта; `make parse-helpf` — только FAQ.
- **Стандарты:** `make load-standards` — v8-code-style и v8std (STANDARDS_REPOS).

## Ingest: переиндексация при перезапуске

Если файлы переиндексируются при каждом перезапуске:

1. **Кэш ингеста** — только **Redis** (REDIS_URL или REDIS_HOST обязательны для ingest-worker и mcp). SQLite для кэша не используется. В Docker Redis поднимается вместе с mcp и ingest-worker (`make up` → qdrant + mcp + redis; `make ingest-up` → + ingest-worker).
2. **INGEST_CACHE_FILE** — путь к каталогу маркеров (load_*.running, load_*.status.json); сами данные кэша в Redis.
3. **Ошибка кэша** — при недоступности Redis (RuntimeError) проверьте REDIS_URL/REDIS_HOST и что контейнер redis запущен.
4. **Распаковка по умолчанию** — ingest пишет в **data/unpacked** (DATA_UNPACKED_DIR) структуру **version/stem** (run_unpack_sync), затем run_ingest_from_unpacked индексирует из неё. Команда **ingest-from-unpacked** ожидает именно эту структуру; вывод **unpack-dir** (version/lang/name) с ней не совместим. INGEST_USE_TEMP=1 — временная папка с удалением после индексации.
5. **Watchdog** — состояние (hbk, standards, snippets) хранится в Redis; при рестарте неизменённые .hbk пропускаются по кэшу. Следит за **STANDARDS_DIR** и **SNIPPETS_DIR**; при изменении нескольких каталогов запускает load-standards, load-snippets и/или ingest **параллельно**.
6. **reinit --force** — стирает коллекции и кэш, затем init; полная переиндексация ожидаема.
7. **Сброс только Qdrant** (volume пересоздан, Redis-кэш остался): справка не восстанавливается (ingest пропускает по кэшу). Решение: `reinit --force` или очистить ключи ingest/snippets в Redis и запустить ingest. Подробно: `docs/ingest-troubleshooting.md` §5.
8. **Сниппеты/стандарты грузятся при каждом старте:** раньше watchdog и кэш load-snippets опирались на **mtime** (время изменения файла). После перезапуска контейнера или нового монтирования volume mtime мог меняться → «каталог изменился» → load-snippets запускался каждый раз. Теперь: подпись каталога в кэше — по **(path, size)**; watchdog сравнивает состояние по **path → size**. После рестарта те же файлы с теми же размерами не считаются изменёнными.
9. **«Snippets: loading…» висит, хотя загрузка давно закончилась:** дашборд показывает «loading», пока существует файл-маркер `load_snippets.running` (создаётся при старте load-snippets, удаляется в `finally`). Если процесс упал (SIGKILL и т.п.) до снятия маркера, статус «loading» остаётся. Маркер считается **устаревшим** через 10 минут (по mtime файла); тогда дашборд перестаёт показывать «loading». Вручную можно удалить файл в каталоге маркеров (INGEST_CACHE_FILE указывает на каталог). Во время загрузки дашборд показывает прогресс в pts (например «Snippets: loading 120/500 pts», «Standards: loading 45/200 pts»).

### Ingest завис (0 done, прогресс не растёт)

Если **dashboard** показывает «embedding», 4500/25503 pts и **Summary: 13 tasks │ 0 done** долго без изменений:

1. **Проверить, жив ли процесс и логи:** Docker — основной лог ingest в контейнере: `docker exec <ingest-worker-container> tail -200 /app/var/log/ingest.log`. Ищите ошибки: **Bus error / exit -7** (SIGBUS — не только OOM: возможны mmap, диск/NFS, SQLite; см. `docs/ingest-troubleshooting.md` §7), 429 (rate limit), timeout, connection refused.
2. **Если воркер упал** — статус в кэше (ingest_current) остаётся последним записанным; новый запуск ingest перезапишет его. Запустите ingest заново: `make ingest` (или `make ingest-up` и дождитесь выполнения).
3. **Rate limit (429)** — уменьшите `EMBEDDING_BATCH_SIZE` (например 32) и/или `EMBEDDING_WORKERS` (1–2); при необходимости увеличьте `EMBEDDING_TIMEOUT`.
4. **Долгая пауза на одном файле** — API эмбеддингов может отвечать медленно или с Retry-After; после 3 попыток и fallback на deterministic индексация продолжается. Если процесс не пишет логи — возможен deadlock (редко при семафоре 300 с).
5. Подробнее: `docs/ingest-troubleshooting.md`.

## Embedding и индексация

- **Точки интеграции:** indexer (справка), memory.upsert_curated_snippets (snippets, community_help, standards), memory.process_pending, memory._write_long_or_pending (real-time). Все batch-операции используют `get_embedding_batch`; только real-time события — `get_embedding`.
- **Единая логика:** sanitize, truncation 2000 символов, retry при len(vectors)!=len(items), 429+Retry-After, EMBEDDING_MAX_CONCURRENT (семафор), retry с меньшим батчем перед fallback. См. `docs/embedding.md`.
- **Бэкенды:** local, openai_api, deterministic (768 dim без модели), none (плейсхолдер).

## Структура кода

- `src/onec_help/`: пакет (unpack, categories, html2md, tree, indexer, memory, parse_fastcode, parse_helpf, parse_its_v8std, snippet_classifier, standards_loader, watchdog, mcp_server, cli, hbk_container, toc_parser, dashboard_data, dashboard_render).
- `unpack` — 7z, zipfile, ZIP from offset, unzip, scan local headers, **HBK binary container** (источник: alkoleft/hbk-viewer); при контейнере пишет `.toc.json`; `unpack-diag` — диагностика при ошибке; `hbk_container` — чтение бинарного .hbk (FileStorage, PackBlock, Book); `toc_parser` — разбор текста PackBlock TOC в плоский список (path, title_ru/en, breadcrumb, entity_type); `categories` — парсинг `__categories__` и дерево TOC; `html2md` — HTML → Markdown; `tree` — дерево (build_tree_for_web и др.); `indexer` — Qdrant, при наличии `.toc.json` в source_dir подмешивает title/breadcrumb/section_path в payload; `memory` — тройная память; `watchdog` — мониторинг .hbk и pending embeddings; `mcp_server` — FastMCP (search_1c_help, get_1c_help_topic, get_1c_function_info, save_1c_snippet, get_1c_help_related, compare_1c_help и др.). Payload точек при TOC содержит `breadcrumb`, `entity_type`.
- Тесты в `tests/`, покрытие ≥70% (pytest-cov, `--cov-fail-under=70`).
- Фикстуры — минимальный срез справки в `tests/fixtures/help_sample/`.
- При локальном запуске тестов не перезапускайте контейнеры и не используйте продуктовый каталог `data/`: задайте в окружении `INGEST_CACHE_FILE`, `DATA_DIR`, `DATA_UNPACKED_DIR` и при необходимости `STANDARDS_DIR`, `SNIPPETS_DIR` на тестовый каталог (например `$(mktemp -d)`), чтобы тесты не затирали данные.

## MCP и конфиг Cursor

- MCP работает **в контейнере** по протоколу **streamable-http** (порт 8050). Рабочий конфиг: **`.cursor/mcp.json`** с полем `url: "http://localhost:8050/mcp"` (без command/stdio). Пример — `docs/mcp.json.example`. Полный справочник инструментов (параметры, лимиты): `docs/mcp-tools-reference.md`.
- **Skill и Rules:** примеры для индексации и синхронизации — `docs/cursor-examples/`. Папка `.cursor/` исключена из git; при настройке Cursor скопируйте содержимое `docs/cursor-examples/` в `.cursor/skills/` и `.cursor/rules/`. При доработке MCP или workflow — обновляйте `docs/cursor-examples/` как зависимость.
- **Рекомендуемый порядок вызовов:**
  1. Ответ с кодом — `get_1c_code_answer` (при необходимости `code_only=True`).
  2. **При нерелевантных результатах get_1c_code_answer** — вызвать `search_1c_help_keyword` с точным именем API (например `Тип.Метод`), затем `get_1c_help_topic(topic_path)` по `path` из результата.
  3. Недостаток деталей — `get_1c_help_topic(topic_path)` (параметр `topic_path`, не `path`).
  4. Точные имена API — `search_1c_help_keyword` с полным именем (в т.ч. `Тип.Метод`).
  5. Несколько совпадений в `get_1c_function_info` — указывать `choose_index`.
  6. После генерации рабочего кода — обязательно вызывать `save_1c_snippet` для сохранения полезных примеров (улучшает последующие ответы get_1c_code_answer).
- **Типовые ловушки:** ПрочитатьJSON возвращает Структуру по умолчанию — для Соответствия указывать `ПрочитатьВСоответствие=Истина`. HTTPСоединение.Получить — только на сервере. Имена методов вида `Тип.Метод` передавать целиком в `search_1c_help_keyword`.
- **Качество ответов и индексация:** при частичной индексации в выдаче только уже проиндексированные версии/разделы; для точных фактов и имён API предпочитать `search_1c_help_keyword` + `get_1c_help_topic`. Подробно: `docs/quality-and-pitfalls-analysis.md`.
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
- **Сохранять рабочий код 1С:** при выдаче исполняемого примера 1С, которого нет в базовых сниппетах, **обязательно** вызывать `save_1c_snippet` с кодом и описанием — это улучшит `get_1c_code_answer` в следующих сессиях. Если результат использован как финальный код — вызвать save_1c_snippet после проверки (например после document_diagnostics).
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

`get_1c_code_answer` / `search_1c_help_keyword` → реализация → `document_diagnostics` → при ERROR/WARNING: исправить и повторить diagnostics до чистоты → `save_1c_snippet` (если переиспользуемо) → опционально unit-тест 1С (YaxUnit) или BDD/сценарий (Vanessa-Automation). См. `docs/1c-testing-guide.md`.

### Цикл «Рефакторинг»

`call_graph` + `project_analysis` → `document_diagnostics` (базовое состояние) → правка одного файла → `document_diagnostics` → при ERROR: исправить и повторить → после batch: `did_change_watched_files` → следующий файл.

### Слой тестирования

- **BSL LS:** `document_diagnostics` — статический анализ (не runtime). Вызывать после каждой правки; цикл до чистоты.
- **Python (onec_help):** `PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70`; `ruff check src tests && ruff format --check src tests`. При падении покрытия — добавить тесты.
- **1C runtime:** YaxUnit (unit-тесты процедур/функций; искать в `Tests/`), Vanessa-Automation (BDD, xdd, UI; искать в `features/`, `BDD/`), CoverageBSL. При новой логике — предлагать unit (YaxUnit) или сценарий (Vanessa). Подробно: `docs/1c-testing-guide.md`.
