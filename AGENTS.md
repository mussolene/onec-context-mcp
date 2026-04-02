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
- **Метаданные 1С:** использовать артефакт [tools/1c/MetadataExport.epf](/Users/maxon/git/me/1c_hbk_helper/tools/1c/MetadataExport.epf). Primary route — **MetadataExport.epf → KD 2.0 XML export → `kd2-snapshot-build` → `metadata-graph-build --source-format kd2-snapshot`**. Прямой `metadata-graph-build /path/export.xml --source-format kd2-xml` тоже допустим. Старый route через `data/config` / `ONEC_CONFIG_SOURCE_DIR` и краулер выгрузки в файлы считать **deprecated fallback**. Подробно: [docs/reference/metadata-export.md](/Users/maxon/git/me/1c_hbk_helper/docs/reference/metadata-export.md).
## Ingest: переиндексация при перезапуске

Если файлы переиндексируются при каждом перезапуске:

1. **Кэш ингеста** — только **Redis** (REDIS_URL или REDIS_HOST обязательны для ingest-worker и mcp). SQLite для кэша не используется. В Docker Redis поднимается вместе с mcp и ingest-worker (`make up` → qdrant + mcp + redis; `make ingest-up` → + ingest-worker).
2. **INGEST_CACHE_FILE** — путь к каталогу маркеров (load_*.running, load_*.status.json); сами данные кэша в Redis.
3. **Ошибка кэша** — при недоступности Redis (RuntimeError) проверьте REDIS_URL/REDIS_HOST и что контейнер redis запущен.
4. **Распаковка по умолчанию** — ingest пишет в **data/unpacked** (DATA_UNPACKED_DIR) структуру **version/stem** (run_unpack_sync), затем run_ingest_from_unpacked индексирует из неё. Команда **ingest-from-unpacked** ожидает именно эту структуру; вывод **unpack-dir** (version/lang/name) с ней не совместим. INGEST_USE_TEMP=1 — временная папка с удалением после индексации.
5. **Watchdog** — работает **только в контейнере ingest-worker** и **только по cron** (раз в 10 мин: `watchdog --once`), без постоянно крутящегося процесса. Состояние (hbk, standards, snippets, **metadata**) хранится в Redis (ключи `watchdog:state:*`). Следит за **STANDARDS_DIR**, **SNIPPETS_DIR** и **ONEC_CONFIG_SOURCE_DIR** (deprecated files route, по умолчанию data/config); при изменении запускает load-standards, load-snippets, ingest и/или metadata-graph-build. Для нового primary route лучше явно запускать `kd2-snapshot-build` и затем `metadata-graph-build --source-format kd2-snapshot`. Локально можно запускать `python -m onec_help watchdog` (бесконечный цикл) или `watchdog --once` (один проход). Если metadata-graph-build не запускается при наличии выгрузки в data/config — в Redis уже сохранено состояние «каталог обработан». Сброс и немедленный запуск: **`make reset-metadata-watchdog`** (нужен **`make ingest-up`**). Ручной запуск: **`make metadata-build`**. Диагностика: **`make metadata-watchdog-debug`**.
6. **reinit --force** — стирает коллекции и кэш, затем init; полная переиндексация ожидаема.
7. **Сброс только Qdrant** (volume пересоздан, Redis-кэш остался): справка не восстанавливается (ingest пропускает по кэшу). Решение: `reinit --force` или очистить ключи ingest/snippets в Redis и запустить ingest. Подробно: `docs/ingest-troubleshooting.md` §5.
8. **Сниппеты/стандарты грузятся при каждом старте:** раньше watchdog и кэш load-snippets опирались на **mtime** (время изменения файла). После перезапуска контейнера или нового монтирования volume mtime мог меняться → «каталог изменился» → load-snippets запускался каждый раз. Теперь: подпись каталога в кэше — по **(path, size)**; watchdog сравнивает состояние по **path → size**. После рестарта те же файлы с теми же размерами не считаются изменёнными.
9. **«Snippets: loading…» висит, хотя загрузка давно закончилась:** дашборд показывает «loading», пока существует файл-маркер `load_snippets.running` (создаётся при старте load-snippets, удаляется в `finally`). Если процесс упал (SIGKILL и т.п.) до снятия маркера, статус «loading» остаётся. Маркер считается **устаревшим** через 10 минут (по mtime файла); тогда дашборд перестаёт показывать «loading». Вручную можно удалить файл в каталоге маркеров (INGEST_CACHE_FILE указывает на каталог). Во время загрузки дашборд показывает прогресс в pts (например «Snippets: loading 120/500 pts», «Standards: loading 45/200 pts»).
10. **Метаданные: в дашборде 0 points в onec_config_metadata** — в stderr при `metadata-graph-build` смотрите: **objects: N** (если 0 — краулер не нашёл объекты в ONEC_CONFIG_SOURCE_DIR); **Qdrant: host:port** (должен совпадать с тем, откуда дашборд читает: в Docker ingest-worker использует `qdrant:6333`); **embedding returned 0 vectors** — API эмбеддингов недоступен или вернул пустой ответ (EMBEDDING_API_URL, Ollama); **metadata-graph-build: upserted X/Y** — при успехе должны появиться строки по батчам. Recreate коллекции выполняется **только после** сборки точек, чтобы при сбое до upsert не оставлять пустую коллекцию. При 400 от Qdrant — проверьте payload (в коде убран `null` через `_payload_no_none`). Таймаут: `QDRANT_TIMEOUT=600 make metadata-build`. **Пустая конфигурация** (только Configuration.xml или config.json, без папок Documents/Catalogs и т.д.) индексируется как **одна точка** с object_type=Configuration и именем/версией — так версия отображается в списке версий и в get_metadata_config_versions.

### Ingest завис (0 done, прогресс не растёт)

Если **dashboard** показывает «embedding», 4500/25503 pts и **Summary: 13 tasks │ 0 done** долго без изменений:

1. **Проверить, жив ли процесс и логи:** Docker — основной лог ingest в контейнере: `docker exec <ingest-worker-container> tail -200 /app/var/log/ingest.log`. Ищите ошибки: **Bus error / exit -7** (SIGBUS — не только OOM: возможны mmap, диск/NFS, SQLite; см. `docs/ingest-troubleshooting.md` §7), 429 (rate limit), timeout, connection refused.
2. **Если воркер упал** — статус в кэше (ingest_current) остаётся последним записанным; новый запуск ingest перезапишет его. Запустите ingest заново: `make ingest` (или `make ingest-up` и дождитесь выполнения).
3. **Rate limit (429)** — уменьшите `EMBEDDING_BATCH_SIZE` (например 32) и/или `EMBEDDING_WORKERS` (1–2); при необходимости увеличьте `EMBEDDING_TIMEOUT`.
4. **Долгая пауза на одном файле** — API эмбеддингов может отвечать медленно или с Retry-After; после 3 попыток и fallback на deterministic индексация продолжается. Если процесс не пишет логи — возможен deadlock (редко при семафоре 300 с).
5. Подробнее: `docs/ingest-troubleshooting.md`.

## Embedding и индексация

- **Точки интеграции:** indexer (справка), memory.upsert_curated_snippets (snippets, community_help, standards), memory.process_pending, memory._write_long_or_pending (real-time). Все batch-операции используют `get_embedding_batch`; только real-time события — `get_embedding`.
- **Единая логика:** sanitize, truncation 2000 символов, retry при len(vectors)!=len(items), 429+Retry-After, EMBEDDING_MAX_CONCURRENT (семафор), retry с меньшим батчем перед fallback. См. `docs/reference/embedding.md`.
- **Бэкенды:** local, openai_api, deterministic (768 dim без модели), none (плейсхолдер).

## Структура кода

- `src/onec_help/`: пакет (unpack, categories, html2md, tree, indexer, memory, parse_fastcode, parse_helpf, parse_its_v8std, snippet_classifier, standards_loader, watchdog, mcp_server, cli, hbk_container, toc_parser, dashboard_data, dashboard_render).
- `unpack` — 7z, zipfile, ZIP from offset, unzip, scan local headers, **HBK binary container** (источник: alkoleft/hbk-viewer); при контейнере пишет `.toc.json`; `unpack-diag` — диагностика при ошибке; `hbk_container` — чтение бинарного .hbk (FileStorage, PackBlock, Book); `toc_parser` — разбор текста PackBlock TOC в плоский список (path, title_ru/en, breadcrumb, entity_type); `categories` — парсинг `__categories__` и дерево TOC; `html2md` — HTML → Markdown; `tree` — дерево (build_tree_for_web и др.); `indexer` — Qdrant, при наличии `.toc.json` в source_dir подмешивает title/breadcrumb/section_path в payload; `memory` — тройная память; `watchdog` — мониторинг .hbk и pending embeddings; `mcp_server` — FastMCP (search_1c_help, get_1c_help_topic, get_1c_function_info, save_1c_snippet, get_1c_help_related, compare_1c_help и др.). Payload точек при TOC содержит `breadcrumb`, `entity_type`.
- Тесты в `tests/`, покрытие ≥77% (pytest-cov, `--cov-fail-under=77`).
- Фикстуры — минимальный срез справки в `tests/fixtures/help_sample/`.
- При локальном запуске тестов не перезапускайте контейнеры и не используйте продуктовый каталог `data/`: задайте в окружении `INGEST_CACHE_FILE`, `DATA_DIR`, `DATA_UNPACKED_DIR` и при необходимости `STANDARDS_DIR`, `SNIPPETS_DIR` на тестовый каталог (например `$(mktemp -d)`), чтобы тесты не затирали данные.

## MCP и конфиг Cursor

- MCP работает **в контейнере** по протоколу **streamable-http** (порт 8050). Рабочий конфиг: **`.cursor/mcp.json`** с полем `url: "http://localhost:8050/mcp"` (без command/stdio). Пример — `docs/reference/mcp.json.example`. Полный справочник инструментов (параметры, лимиты): `docs/reference/mcp-tools-reference.md`. Исчерпывающий отчёт по полноте 1c-help и внешнего `lsp-bsl-bridge`, результаты прогонов и рекомендации: **`docs/archive/mcp-1c-help-tools-report.md`**. `lsp-bsl-bridge` считается **внешним подключаемым MCP**, а не частью продукта этого репозитория: здесь меняются только `1c-help`, self-documentation и интеграционный workflow. Для AI-агента канонический entry point — `get_1c_quick_guide`; длинные guide/prompts оставлять для человека и onboarding. При `MCP_CURSOR_DOCS_PATH` (в Docker по умолчанию `/app/docs`) MCP отдаёт руководства через промпты `get_mcp_workflow_guide`, `get_mcp_tools_tips`, `get_mcp_tools_summary`, `get_mcp_guides_bundle` (самодокументируемый MCP).
- **Skill и Rules:** примеры для индексации и синхронизации — `docs/cursor-examples/`. Папка `.cursor/` исключена из git; при настройке Cursor скопируйте содержимое `docs/cursor-examples/` в `.cursor/skills/` и `.cursor/rules/`. При доработке MCP или workflow — обновляйте `docs/cursor-examples/` как зависимость.
- **Рекомендуемый порядок вызовов:**
  1. Для AI-сессии — `get_1c_quick_guide(task="develop"|"refactor"|"test")`.
  2. Точный API/идентификатор — `get_1c_api_answer(name)` или `search_1c_help_keyword` с полным именем (`Тип.Метод`), затем `get_1c_help_topic(topic_path)` по `path` из результата.
  3. Локальный anti-hallucination context — `get_1c_task_context(query, file_uri, symbol_name)`.
  4. Нужны стандарты явно — `search_1c_standards(query)`. Нужны примеры кода — `search_1c_snippets(query)`. Legacy umbrella: `search_1c_memory(query, domains="standards,snippets")`.
  5. Нужны объекты конфигурации — `search_1c_metadata_exact` → `get_1c_metadata_object`; natural language — `search_1c_metadata_semantic`; реквизиты/табличные части — `search_1c_metadata_fields`.
  6. Внешняя проверка/навигация по коду — `document_diagnostics`, `project_analysis`, `symbol_explore`, `get_range_content`. Не проектировать workflow так, будто этот репозиторий управляет поведением `lsp-bsl-bridge`.
- **Типовые ловушки:** ПрочитатьJSON возвращает Структуру по умолчанию — для Соответствия указывать `ПрочитатьВСоответствие=Истина`. HTTPСоединение.Получить — только на сервере. Имена методов вида `Тип.Метод` передавать целиком в `search_1c_help_keyword`.
- **Качество ответов и индексация:** при частичной индексации в выдаче только уже проиндексированные версии/разделы; для точных фактов и имён API предпочитать `search_1c_help_keyword` + `get_1c_help_topic`. Подробно: `docs/archive/quality-and-pitfalls-analysis.md`.
- **Почему в ответах нет стандартов и сниппетов:** инструменты `search_1c_standards`, `search_1c_snippets` и `search_1c_memory` читают коллекцию Qdrant **onec_help_memory**. Её заполняют команды **load-snippets** (SNIPPETS_DIR, parse-fastcode/parse-helpf) и **load-standards** (v8-code-style, v8std). Если эти команды не запускались или завершились с ошибкой (например, нет embedding API), коллекция пуста. Проверка: `get_1c_help_index_status` — в выводе должна быть строка «Memory (**onec_help_memory**): **N** points». При N=0 или отсутствии такой строки выполните `make load-snippets` и `make load-standards` (или через init/watchdog); убедитесь, что EMBEDDING_API_URL доступен при загрузке.
- **Маршрут памяти:** для стандартов предпочитать `search_1c_standards`, для примеров кода — `search_1c_snippets`, umbrella `search_1c_memory(query, domains="standards,snippets")` оставить только как fallback.
- **Статьи ITS (папка standards/its-v8std):** в **data/standards/its-v8std** могут лежать .md статьи (например, выгруженные с its.1c.ru/db/v8std или сохранённые после `load-standards --its-v8std`). Они попадают в **onec_help_memory** только если при запуске **load-standards** папка **STANDARDS_DIR/its-v8std** существует (например, `data/standards/its-v8std` при STANDARDS_DIR=data/standards). load-standards по умолчанию загружает репо v8-code-style и v8std, затем **дополнительно** обходит `STANDARDS_DIR/its-v8std` и добавляет все .md в индекс. Если MCP работает в Docker, нужен монтирование, при котором эта папка видна контейнеру (например, `.:/app` и STANDARDS_DIR=/app/data/standards). В логе load-standards при успешной подгрузке с диска будет строка «ITS from disk: N items ← …/its-v8std». Если в ответах нет статей ITS — перезапустите `make load-standards` и проверьте, что в выводе есть «ITS from disk: …».
- **При добавлении новых MCP-сервисов** их нужно прописать в `.cursor/mcp.json`: для удалённого сервера — запись в `mcpServers` с полем `url`; для локального — `command`, `args`, при необходимости `env`. После изменений конфига Cursor перезапускают.

### Чек-лист сценариев 1c-help (для ассистента)

- **Только справка и память:** ingest выполнен, Qdrant доступен → `get_1c_help_index_status` показывает топики и memory → основной AI-маршрут: `get_1c_quick_guide`, `get_1c_api_answer`, `search_1c_help_keyword`, `get_1c_help_topic`, `search_1c_standards`, `search_1c_snippets`, `search_1c_memory`, `get_1c_function_info`, `compare_1c_help`, `get_module_info`, `get_form_metadata`. `save_1c_snippet` — только для реально переиспользуемого и проверенного кода.
- **Справка + метаданные конфигурации:** основной вариант — запустить [tools/1c/MetadataExport.epf](/Users/maxon/git/me/1c_hbk_helper/tools/1c/MetadataExport.epf), получить KD 2.0 XML, затем `kd2-snapshot-build` → `metadata-graph-build` (или прямой `metadata-graph-build --source-format kd2-xml`) → в `get_1c_help_index_status` видна коллекция onec_config_metadata. Exact-first поиск по имени/идентификатору — `search_1c_metadata_exact`; natural-language — `search_1c_metadata_semantic`; поля/реквизиты — `search_1c_metadata_fields`. `config_version` опционален, если в графе одна версия (подставляется автоматически). Route через выгрузку «в файлы» и `config_crawler` считать deprecated fallback. `get_1c_context_bundle` — legacy broad-context.
- **Написание кода:** справка (и при необходимости метаданные) → генерация/адаптация кода → проверка через lsp-bsl-bridge (`document_diagnostics`) → при успехе и переиспользовании — `save_1c_snippet`.
- **Поддержка/рефакторинг:** по необходимости — `project_analysis`, `symbol_explore`, `call_graph` (lsp-bsl-bridge); для справки по API — те же инструменты 1c-help; после правок — `document_diagnostics` до чистоты и `did_change_watched_files` при batch.

## Безопасность

- MCP по HTTP не имеет аутентификации; рассчитан **только** на доверенную сеть (localhost/VPN). При экспозиции в интернет — обязателен обратный прокси с аутентификацией.
- Рекомендуемый вариант для HTTP-транспорта MCP:
  - MCP-сервер слушает **только localhost** (127.0.0.1:8050) или внутреннюю Docker-сеть.
  - Снаружи открыт только reverse proxy (nginx/Traefik/Caddy) с TLS и аутентификацией (basic/OIDC/мутуальный TLS).
  - Cursor и другие клиенты подключаются к proxy-URL; прямой доступ к контейнеру mcp снаружи отключён.
- Qdrant и Redis по умолчанию должны быть видимы только из внутренней сети (Docker network/VPN). Если Qdrant всё же открывается наружу — только за TLS/прокси и с включённой аутентификацией согласно документации Qdrant.

## Конфиденциальность и NDA

- **Embedding API:** по умолчанию Ollama (localhost:11434), модель nomic-embed-text-v2-moe. Текст справки и поисковые запросы отправляются на этот сервис; при конфиденциальных данных используйте on-prem (EMBEDDING_API_URL на внутренний хост).
- **Memory (MEMORY_ENABLED=1):** история сессий (topic_path, save_snippet, exchange) хранится в JSONL и Qdrant. Учитывайте политику хранения и доступ к этим данным.
- **save_1c_snippet:** сохранённый код пишется в memory. При SAVE_SNIPPET_TO_FILES=1 — также в SNIPPETS_DIR. При конфиденциальном коде настройте SNIPPETS_DIR и MEMORY_BASE_PATH в защищённое место.
- **Конфигурация 1С и стандарты ITS:** каталоги ONEC_CONFIG_SOURCE_DIR (`data/config`) и STANDARDS_DIR (в т.ч. `its-v8std`) относятся к NDA‑периметру; коллекция `onec_config_metadata` в Qdrant должна размещаться только во внутренней сети/под VPN, экспорт точек и исходных XML/статей ITS наружу допускается только по отдельному согласованию.
- **Логи:** в production (PRODUCTION=1) в ответах API и логах не раскрываются полные пути и текст исключений.

## Правила

- Язык кода и комментариев — по контексту (рус/англ). Пути и конфигурация — только через аргументы и env, без хардкода.
- **Сохранять рабочий код 1С:** `save_1c_snippet` использовать только для реально переиспользуемого и уже проверенного результата. Не считать сохранение каждого ответа обязательным шагом.
- Не трогать план в `.cursor/plans/`. При доработках сохранять совместимость с docker-compose и Qdrant. При изменении MCP или workflow — проверить и обновить `docs/cursor-examples/` (skill, rules).
- Использовать subagent'ы при необходимости для объёмных задач.

### Работа с 1С-кодом

- **Два MCP:** `1c-help` — основной MCP этого репозитория; внешний `lsp-bsl-bridge` подключается для проверки/навигации (`document_diagnostics`, `project_analysis`, `symbol_explore`, `get_range_content`). Если 1c-help недоступен (нет индекса) — опереться на внешний LSP и memory, но не считать это основным маршрутом.
- **После правок 1С:** вызывать `document_diagnostics` для проверки ошибок, предупреждений и соответствия стандартам BSL LS. URI для Docker: `file:///projects/<path>/Module.bsl` (volume `.:/projects`).
- **Стандарты:** учитывать правила 1С (BSL LS diagnostics + v8-code-style и v8std из `load-standards`).

## Workflow разработки 1С с BSL LS

Циклы с проверками; при ошибках — возврат к шагу исправления.

1. **Индексация.** `make up` или `docker compose up -d`. Внешний BSL LS: `make bsl-start` (отдельно), volume `.:/projects`. Дождаться готовности LSP.
2. **Ориентирование.** `project_analysis` — поиск символов/файлов; `symbol_explore` — детали по символу; `get_range_content` — устойчивый способ взять локальный фрагмент. `call_graph` не считать обязательным шагом.

### Цикл «Написание кода»

`get_1c_api_answer` / `search_1c_help_keyword` / `get_1c_help_topic` + при необходимости `search_1c_standards` / `search_1c_snippets` / `get_1c_task_context` → реализация → внешний `document_diagnostics` → при ERROR/WARNING: исправить и повторить diagnostics до чистоты → `save_1c_snippet` только если код действительно переиспользуемый → опционально unit-тест 1С (YaxUnit) или BDD/сценарий (Vanessa-Automation). См. `docs/reference/1c-testing-guide.md`.

### Цикл «Рефакторинг»

`project_analysis` + `symbol_explore` + `get_range_content` → `document_diagnostics` (базовое состояние) → правка одного файла → `document_diagnostics` → при ERROR: исправить и повторить → после batch: `did_change_watched_files` → следующий файл.

### Слой тестирования

- **BSL LS:** `document_diagnostics` — статический анализ (не runtime). Вызывать после каждой правки; цикл до чистоты.
- **Python (onec_help):** `PYTHONPATH=src python3 -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=77`; `ruff check src tests && ruff format --check src tests`. При падении покрытия — добавить тесты. Для проверки инструментов на живом MCP: поднять сервисы (`make up` и т.д.), затем `MCP_INTEGRATION=1 PYTHONPATH=src python3 -m pytest tests/test_mcp_integration.py tests/test_mcp_functional_crypto.py -v --no-cov` (см. `docs/archive/mcp-1c-help-verification-report.md`).
- **1C runtime:** YaxUnit (unit-тесты процедур/функций; искать в `Tests/`), Vanessa-Automation (BDD, xdd, UI; искать в `features/`, `BDD/`), CoverageBSL. При новой логике — предлагать unit (YaxUnit) или сценарий (Vanessa). Подробно: `docs/reference/1c-testing-guide.md`.
