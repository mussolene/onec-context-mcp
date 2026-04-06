# AGENTS.md — 1C Help MCP

## Назначение проекта

- Справка 1С: распаковка .hbk (7z), разбор HTML в structured JSONL, индексация structured help в Qdrant, MCP-сервер для поиска/ответов по API.
- Конфигурация через переменные окружения. БД — Qdrant в docker-compose.
- Дальнейшие этапы: один–два MCP по кодовой базе и метаданным 1С (задел в README).

## Команды и сценарии

- **Единая точка входа:** **ingest** — загрузка/обновление structured help (поиск .hbk в HELP_SOURCE_BASE, временная распаковка HTML, JSONL, Qdrant). **reinit --force** — полная перезагрузка: очистка коллекций и кэша, затем init (ingest + load-snippets + load-standards). Без миграций и без постоянного runtime-каталога unpacked.
- **Локально:** `python -m onec_help ingest|reinit|init|dashboard|mcp|unpack|build-index|load-snippets|load-standards|watchdog ...`
- **init** — ingest, load-snippets и load-standards запускаются **параллельно** (асинхронно). Не стирает данные.
- **reinit --force** — очистка коллекций и cache, затем init. Для перезапуска «с нуля».
- **Docker:** по умолчанию `make up` — только **qdrant** и **mcp**. Для индексации и watchdog: **`make ingest-up`** (профиль **ingest**: контейнер **ingest-worker** с **cron** — при старте **`watchdog --once`**, далее **`watchdog --once` каждые 10 мин**, полный **`ingest` раз в сутки в 3:00**). **`make ingest`** — опционально: немедленный полный ingest в уже запущенный ingest-worker, без ожидания cron. Полная перезагрузка: `make reinit ARGS='--force'`. В **full**-режиме фоновые задачи живут в одном контейнере **mcp**. BSL LS — `make bsl-start`.
- **dashboard** — дашборд (Tasks, Errors, Qdrant, версии 1С): `--once` один кадр, иначе Live с `--interval`.
- **read-hbk-container** — чтение .hbk как бинарного контейнера (alkoleft/hbk-viewer): сущности, извлечение в каталог, TOC в JSON (вспомогательная команда).
- **Сниппеты:** ./data/snippets, parse-fastcode/parse-helpf пишут туда, `load-snippets` загружает. `make snippets` — оба сайта; `make parse-helpf` — только FAQ.
- **Стандарты:** `make load-standards` — v8-code-style и v8std (STANDARDS_REPOS).
- **Метаданные 1С:** использовать артефакт [tools/1c/MetadataExport.epf](tools/1c/MetadataExport.epf). Primary route — **одна папка `data/kd2`**: туда кладётся KD 2.0 XML export, а derived snapshot автоматически пишется **по конфигурациям отдельно** в `data/kd2/snapshots/<config-key>/manifest.json|objects.jsonl|fields.jsonl`. `metadata-graph-build data/kd2` и `watchdog` сами обновляют snapshot при изменении XML. Явный `kd2-snapshot-build` оставлен как ручная утилита для одного XML. Старый route через `data/config` / `ONEC_CONFIG_SOURCE_DIR` и краулер выгрузки в файлы считать **deprecated fallback**. Подробно: [docs/reference/metadata-export.md](docs/reference/metadata-export.md).
- **Structured help:** после изменений extractor запускать `python -m onec_help structured-help-scorecard --output-file data/help_structured/scorecard.json`. Это официальный stop-check для `api_objects|members|examples|links`: он считает coverage, path coverage и benchmark exact hit rate. Full topic layer (`onec_help`) считать cold fallback, а не основной exact API route. Подробно: [docs/reference/structured-help-scorecard.md](docs/reference/structured-help-scorecard.md).
- **Structured help source:** primary route для `build-api-structured` — **unpacked HTML**. Канонический persistent слой — `data/help_structured/*.jsonl`; `data/unpacked` использовать только как временный или ручной промежуточный каталог. План миграции и целевые stop-conditions: [docs/reference/structured-help-jsonl-first-plan.md](docs/reference/structured-help-jsonl-first-plan.md). Snapshot **v5** (`onec_help_structured_api_v5`): `topic_path` без префикса версии платформы, дедуп по content-hash с полем `versions`; при вызове MCP с `version` подходит запись, если версия входит в `versions`.
## Ingest: переиндексация при перезапуске

Если файлы переиндексируются при каждом перезапуске:

1. **Кэш ингеста** — только **Redis** (REDIS_URL или REDIS_HOST обязательны для ingest-worker и mcp). SQLite для кэша не используется. В Docker Redis поднимается вместе с mcp и ingest-worker (`make up` → qdrant + mcp + redis; `make ingest-up` → + ingest-worker).
2. **INGEST_CACHE_FILE** — путь к каталогу маркеров (load_*.running, load_*.status.json); сами данные кэша в Redis.
3. **Ошибка кэша** — при недоступности Redis (RuntimeError) проверьте REDIS_URL/REDIS_HOST и что контейнер redis запущен.
4. **Распаковка по умолчанию** — ingest использует **временный** HTML workspace и после успешной сборки structured JSONL удаляет его. Постоянный runtime-layer — `data/help_structured`. Команда **ingest-from-unpacked** остаётся для ручного сценария: она ожидает структуру **version/stem**; вывод **unpack-dir** (version/lang/name) с ней не совместим.
5. **Watchdog** — работает **только в контейнере ingest-worker** и **только по cron** (раз в 10 мин: `watchdog --once`), без постоянно крутящегося процесса. Состояние (hbk, standards, snippets, **metadata**) хранится в Redis (ключи `watchdog:state:*`). Следит за **STANDARDS_DIR**, **SNIPPETS_DIR** и **ONEC_CONFIG_SOURCE_DIR** (по умолчанию `data/kd2`); при изменении запускает load-standards, load-snippets, ingest и/или metadata-graph-build. Для primary route `data/kd2` достаточно положить новый KD2 XML: watchdog сам обновит snapshot в этой же папке и затем запустит `metadata-graph-build`. Локально можно запускать `python -m onec_help watchdog` (бесконечный цикл) или `watchdog --once` (один проход). Если metadata-graph-build не запускается при наличии выгрузки — в Redis уже сохранено состояние «каталог обработан». Сброс и немедленный запуск: **`make reset-metadata-watchdog`** (нужен **`make ingest-up`**). Ручной запуск: **`make metadata-build`**. Диагностика: **`make metadata-watchdog-debug`**.
6. **reinit --force** — стирает коллекции и кэш, затем init; полная переиндексация ожидаема.
7. **Сброс только Qdrant** (volume пересоздан, Redis-кэш остался): справка не восстанавливается (ingest пропускает по кэшу). Решение: `reinit --force` или очистить ключи ingest/snippets в Redis и запустить ingest. Подробно: `docs/ingest-troubleshooting.md` §5.
8. **Сниппеты/стандарты грузятся при каждом старте:** раньше watchdog и кэш load-snippets опирались на **mtime** (время изменения файла). После перезапуска контейнера или нового монтирования volume mtime мог меняться → «каталог изменился» → load-snippets запускался каждый раз. Теперь: подпись каталога в кэше — по **(path, size)**; watchdog сравнивает состояние по **path → size**. После рестарта те же файлы с теми же размерами не считаются изменёнными.
9. **«Snippets: loading…» висит, хотя загрузка давно закончилась:** дашборд показывает «loading», пока существует файл-маркер `load_snippets.running` (создаётся при старте load-snippets, удаляется в `finally`). Если процесс упал (SIGKILL и т.п.) до снятия маркера, статус «loading» остаётся. Маркер считается **устаревшим** через 10 минут (по mtime файла); тогда дашборд перестаёт показывать «loading». Вручную можно удалить файл в каталоге маркеров (INGEST_CACHE_FILE указывает на каталог). Во время загрузки дашборд показывает прогресс в pts (например «Snippets: loading 120/500 pts», «Standards: loading 45/200 pts»).
10. **Метаданные: в дашборде 0 points в onec_config_metadata** — в stderr при `metadata-graph-build` смотрите: **objects: N** (если 0 — краулер не нашёл объекты в ONEC_CONFIG_SOURCE_DIR); **Qdrant: host:port** (должен совпадать с тем, откуда дашборд читает: в Docker ingest-worker использует `qdrant:6333`); **embedding returned 0 vectors** — API эмбеддингов недоступен или вернул пустой ответ (EMBEDDING_API_URL, Ollama); **metadata-graph-build: upserted X/Y** — при успехе должны появиться строки по батчам. Recreate коллекции выполняется **только после** сборки точек, чтобы при сбое до upsert не оставлять пустую коллекцию. При 400 от Qdrant — проверьте payload (в коде убран `null` через `_payload_no_none`). Таймаут: `QDRANT_TIMEOUT=600 make metadata-build`. **Пустая конфигурация** (только Configuration.xml или config.json, без папок Documents/Catalogs и т.д.) индексируется как **одна точка** с object_type=Configuration и именем/версией — так версия отображается в списке версий и в get_metadata_config_versions.

### Ingest завис (0 done, прогресс не растёт)

Если **dashboard** показывает «embedding», 4500/25503 pts и **Summary: 13 tasks │ 0 done** долго без изменений:

1. **Проверить, жив ли процесс и логи:** Docker — основной лог ingest в контейнере: `docker exec <ingest-worker-container> tail -200 /app/var/log/ingest.log`. Ищите ошибки: **Bus error / exit -7** (SIGBUS — не только OOM: возможны mmap, диск/NFS, SQLite; см. `docs/ingest-troubleshooting.md` §7), 429 (rate limit), timeout, connection refused.
2. **Если воркер упал** — статус в кэше (ingest_current) остаётся последним записанным; новый запуск ingest перезапишет его. Поднимите **`make ingest-up`** снова (при старте снова отработает **watchdog --once**), либо выполните **`make ingest`** для немедленного полного прогона, когда контейнер уже запущен.
3. **Rate limit (429)** — уменьшите `EMBEDDING_BATCH_SIZE` (например 32) и/или `EMBEDDING_WORKERS` (1–2); при необходимости увеличьте `EMBEDDING_TIMEOUT`.
4. **Долгая пауза на одном файле** — API эмбеддингов может отвечать медленно или с Retry-After; после 3 попыток и fallback на deterministic индексация продолжается. Если процесс не пишет логи — возможен deadlock (редко при семафоре 300 с).
5. Подробнее: `docs/ingest-troubleshooting.md`.

## Embedding и индексация

- **Точки интеграции:** indexer (справка), memory.upsert_curated_snippets (snippets, community_help, standards), memory.process_pending, memory._write_long_or_pending (real-time). Все batch-операции используют `get_embedding_batch`; только real-time события — `get_embedding`.
- **Единая логика:** sanitize, truncation 2000 символов, retry при len(vectors)!=len(items), 429+Retry-After, EMBEDDING_MAX_CONCURRENT (семафор), retry с меньшим батчем перед fallback. См. `docs/reference/embedding.md`.
- **Бэкенды:** local, openai_api, deterministic (768 dim без модели), none (плейсхолдер).

## Структура кода

- `src/onec_help/`: пакет (unpack, categories, html2md, tree, indexer, memory, parse_fastcode, parse_helpf, parse_its_v8std, snippet_classifier, standards_loader, watchdog, mcp_server, cli, hbk_container, toc_parser, dashboard_data, dashboard_render).
- `unpack` — 7z, zipfile, ZIP from offset, unzip, scan local headers, **HBK binary container** (источник: alkoleft/hbk-viewer); при контейнере пишет `.toc.json`; `unpack-diag` — диагностика при ошибке; `hbk_container` — чтение бинарного .hbk (FileStorage, PackBlock, Book); `toc_parser` — разбор текста PackBlock TOC в плоский список (path, title_ru/en, breadcrumb, entity_type); `categories` — парсинг `__categories__` и дерево TOC; `html2md` — общий HTML section parser; `help_structured` — HTML → structured JSONL + structured Qdrant collections; `memory` — тройная память; `watchdog` — мониторинг .hbk и pending embeddings; `mcp_server` — FastMCP (`get_1c_api_answer`, `answer_1c_help_question`, `search_1c_api`, `get_1c_api_object`, `search_1c_standards`, `search_1c_snippets`, `save_1c_snippet`, `compare_1c_help` и др.).
- Тесты в `tests/`, покрытие: порог в `pyproject.toml` (`--cov-fail-under`, сейчас **74%**); целевое **≥77%** — при росте покрытия поднять порог в `addopts`.
- Фикстуры — минимальный срез справки в `tests/fixtures/help_sample/`.
- При локальном запуске тестов не перезапускайте контейнеры и не используйте продуктовый каталог `data/`: задайте в окружении `INGEST_CACHE_FILE`, `DATA_DIR`, `DATA_UNPACKED_DIR` и при необходимости `STANDARDS_DIR`, `SNIPPETS_DIR` на тестовый каталог (например `$(mktemp -d)`), чтобы тесты не затирали данные.

## MCP и конфиг Cursor

- MCP **1c-help** работает **в контейнере** по протоколу **streamable-http** (порт 8050). Рабочий конфиг: **`.cursor/mcp.json`** с полем `url: "http://localhost:8050/mcp"` (без command/stdio). Пример — `docs/reference/mcp.json.example`. Полный справочник инструментов (параметры, лимиты): `docs/reference/mcp-tools-reference.md`. Исторический отчёт по полноте инструментов и прогонам: **`docs/archive/mcp-1c-help-tools-report.md`**. Проверка и стиль **BSL-кода** делаются **BSL Language Server** (CLI `analyze`/`format`, расширение IDE или опционально `make bsl-start` — см. `docs/reference/bsl-ls-mcp-setup.md`); отдельный MCP для LS в этом репозитории не документируется. Для AI-агента канонический entry point — `get_1c_quick_guide`; длинные guide/prompts — для человека и onboarding. При `MCP_CURSOR_DOCS_PATH` (в Docker по умолчанию `/app/docs`) MCP отдаёт руководства через промпты `get_mcp_workflow_guide`, `get_mcp_tools_tips`, `get_mcp_tools_summary`, `get_mcp_guides_bundle` (самодокументируемый MCP).
- **Skill и Rules:** примеры для индексации и синхронизации — `docs/cursor-examples/`. Папка `.cursor/` исключена из git; при настройке Cursor скопируйте содержимое `docs/cursor-examples/` в `.cursor/skills/` и `.cursor/rules/`. При доработке MCP или workflow — обновляйте `docs/cursor-examples/` как зависимость.
- **Рекомендуемый порядок вызовов:**
  1. Для AI-сессии — `get_1c_quick_guide(task="develop"|"refactor"|"test")`.
  2. Точный API/идентификатор — `get_1c_api_answer(name)` (полный текст — `detail="full"`); structured truth-source — `get_1c_api_object(name)`; broad structured lookup — `search_1c_api(query)`; официальные примеры из справки — `search_1c_api(..., include_examples=True)` (по умолчанию уже включено); natural-language factual question — `answer_1c_help_question(question)`.
  3. Curated примеры кода — `search_1c_snippets(query)`.
  4. Локальный anti-hallucination context — `get_1c_task_context(query, file_uri, symbol_name)`.
  5. Нужны стандарты явно — `search_1c_standards(query)`.
  6. Нужны объекты конфигурации — `search_1c_metadata_exact` → `get_1c_metadata_object`; natural language — `search_1c_metadata_semantic`; реквизиты/табличные части — `search_1c_metadata_fields`.
  7. Проверка `.bsl` — BSL Language Server: JAR `analyze`/`format` (`docs/cursor-examples/bsl-language-server-local/SKILL.md`), диагностики IDE или опционально Docker (`make bsl-start`). Навигация — поиск по репозиторию и средства IDE.
- **Типовые ловушки:** ПрочитатьJSON возвращает Структуру по умолчанию — для Соответствия указывать `ПрочитатьВСоответствие=Истина`. HTTPСоединение.Получить — только на сервере. Имена методов вида `Тип.Метод` передавать целиком в `get_1c_api_answer`.
- **Качество ответов и индексация:** runtime route по справке теперь structured DB-first; для точных фактов и имён API предпочитать `get_1c_api_answer`, `answer_1c_help_question` и `search_1c_api`. Исторический анализ старого topic-layer: `docs/archive/quality-and-pitfalls-analysis.md`.
- **Почему в ответах нет стандартов и сниппетов:** инструменты `search_1c_standards` и `search_1c_snippets` читают коллекцию Qdrant **onec_help_memory**. Её заполняют команды **load-snippets** (SNIPPETS_DIR, parse-fastcode/parse-helpf) и **load-standards** (v8-code-style, v8std). Если эти команды не запускались или завершились с ошибкой (например, нет embedding API), коллекция пуста. Проверка: `get_1c_help_index_status` — в выводе должна быть строка «Memory (**onec_help_memory**): **N** points». При N=0 или отсутствии такой строки выполните `make load-snippets` и `make load-standards` (или через init/watchdog); убедитесь, что EMBEDDING_API_URL доступен при загрузке.
- **Маршрут памяти:** для стандартов — `search_1c_standards`, для примеров кода — `search_1c_snippets`.
- **Статьи ITS (папка standards/its-v8std):** в **data/standards/its-v8std** могут лежать .md статьи (например, выгруженные с its.1c.ru/db/v8std или сохранённые после `load-standards --its-v8std`). Они попадают в **onec_help_memory** только если при запуске **load-standards** папка **STANDARDS_DIR/its-v8std** существует (например, `data/standards/its-v8std` при STANDARDS_DIR=data/standards). load-standards по умолчанию загружает репо v8-code-style и v8std, затем **дополнительно** обходит `STANDARDS_DIR/its-v8std` и добавляет все .md в индекс. Если MCP работает в Docker, нужен монтирование, при котором эта папка видна контейнеру (например, `.:/app` и STANDARDS_DIR=/app/data/standards). В логе load-standards при успешной подгрузке с диска будет строка «ITS from disk: N items ← …/its-v8std». Если в ответах нет статей ITS — перезапустите `make load-standards` и проверьте, что в выводе есть «ITS from disk: …».
- **При добавлении новых MCP-сервисов** их нужно прописать в `.cursor/mcp.json`: для удалённого сервера — запись в `mcpServers` с полем `url`; для локального — `command`, `args`, при необходимости `env`. После изменений конфига Cursor перезапускают.

### Чек-лист сценариев 1c-help (для ассистента)

- **Только справка и память:** ingest выполнен, Qdrant доступен → `get_1c_help_index_status` показывает structured API и memory → основной AI-маршрут: `get_1c_quick_guide`, `get_1c_api_answer`, `answer_1c_help_question`, `search_1c_api`, `get_1c_api_object`, `search_1c_standards`, `search_1c_snippets`, `get_1c_task_context`, `compare_1c_help`, `get_module_info`, `get_form_metadata`. `save_1c_snippet` — только для реально переиспользуемого и проверенного кода.
- **Справка + метаданные конфигурации:** основной вариант — запустить [tools/1c/MetadataExport.epf](tools/1c/MetadataExport.epf), получить KD 2.0 XML, затем `kd2-snapshot-build` → `metadata-graph-build` (или прямой `metadata-graph-build --source-format kd2-xml`) → в `get_1c_help_index_status` видна коллекция onec_config_metadata. Exact-first поиск по имени/идентификатору — `search_1c_metadata_exact`; natural-language — `search_1c_metadata_semantic`; поля/реквизиты — `search_1c_metadata_fields`. `config_version` опционален, если в графе одна версия (подставляется автоматически). Route через выгрузку «в файлы» и `config_crawler` считать deprecated fallback. Широкий контекст задачи — `get_1c_task_context` и узкие вызовы help/metadata, без отдельного bundle-tool.
- **Написание кода:** справка (и при необходимости метаданные) → генерация/адаптация кода → BSL LS (`analyze` / IDE) → при успехе и переиспользовании — `save_1c_snippet`.
- **Поддержка/рефакторинг:** навигация по коду (IDE, rg/git grep); для справки по API — 1c-help; после правок — снова BSL LS на затронутых модулях.

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
- **Конфигурация 1С и стандарты ITS:** каталог ONEC_CONFIG_SOURCE_DIR (primary route: `data/kd2`; legacy fallback: `data/config`) и STANDARDS_DIR (в т.ч. `its-v8std`) относятся к NDA‑периметру; коллекция `onec_config_metadata` в Qdrant должна размещаться только во внутренней сети/под VPN, экспорт точек и исходных XML/статей ITS наружу допускается только по отдельному согласованию.
- **Логи:** в production (PRODUCTION=1) в ответах API и логах не раскрываются полные пути и текст исключений.

## Правила

- Язык кода и комментариев — по контексту (рус/англ). Пути и конфигурация — только через аргументы и env, без хардкода.
- **Сохранять рабочий код 1С:** `save_1c_snippet` использовать только для реально переиспользуемого и уже проверенного результата. Не считать сохранение каждого ответа обязательным шагом.
- Не трогать план в `.cursor/plans/`. При доработках сохранять совместимость с docker-compose и Qdrant. При изменении MCP или workflow — проверить и обновить `docs/cursor-examples/` (skill, rules).
- Использовать subagent'ы при необходимости для объёмных задач.

### Работа с 1С-кодом

- **MCP 1c-help** — справка, метаданные, сниппеты, стандарты из этого репозитория. **BSL LS** — отдельно: CLI, IDE или опционально `make bsl-start` (см. `docs/reference/bsl-ls-mcp-setup.md`). Если индекса справки нет — опираться на LS и локальный контекст, но основной маршрут фактов по платформе — 1c-help после ingest.
- **После правок 1С:** прогон BSL LS (`analyze` на каталог/файл или диагностики в IDE) до приемлемого уровня замечаний.
- **Стандарты:** BSL LS + v8-code-style и v8std из `load-standards` (через 1c-help `search_1c_standards`).

## Workflow разработки 1С с BSL LS

Циклы с проверками; при ошибках — возврат к шагу исправления.

1. **Индексация справки.** `make up` или `docker compose up -d` для Qdrant и MCP 1c-help. **Опционально:** `make bsl-start` — отдельный контейнер BSL LS с монтированием `.:/projects:ro`.
2. **Ориентирование по коду.** Поиск по проекту (rg, IDE), чтение модулей по путям выгрузки.

### Цикл «Написание кода»

`get_1c_api_answer` / `answer_1c_help_question` / `search_1c_api` (при необходимости с `include_examples=True`) / `get_1c_api_object` + при необходимости `search_1c_standards` / `search_1c_snippets` / `get_1c_task_context` → реализация → BSL LS `analyze` (или IDE) → исправить критичные замечания → `save_1c_snippet` только если код переиспользуемый → опционально unit-тест 1С (YaxUnit) или BDD (Vanessa-Automation). См. `docs/reference/1c-testing-guide.md`.

### Цикл «Рефакторинг»

Найти символы (IDE/rg) → baseline `analyze` на затронутых путях → правка одного файла → снова `analyze` → повторять до чистоты → следующий файл.

### Слой тестирования

- **BSL LS:** `analyze` (JAR) или диагностики IDE — статический анализ (не runtime). После каждой правки; цикл до приемлемой чистоты.
- **Python (onec_help):** `PYTHONPATH=src python3 -m pytest tests -v --cov=src/onec_help --cov-report=term-missing` (порог покрытия — из `pyproject.toml`); `ruff check src tests && ruff format --check src tests`. При падении покрытия — добавить тесты. Для проверки инструментов на живом MCP: поднять сервисы (`make up` и т.д.), затем `MCP_INTEGRATION=1 PYTHONPATH=src python3 -m pytest tests/test_mcp_integration.py tests/test_mcp_functional_crypto.py -v --no-cov` (см. `docs/archive/mcp-1c-help-verification-report.md`).
- **1C runtime:** YaxUnit (unit-тесты процедур/функций; искать в `Tests/`), Vanessa-Automation (BDD, xdd, UI; искать в `features/`, `BDD/`), CoverageBSL. При новой логике — предлагать unit (YaxUnit) или сценарий (Vanessa). Подробно: `docs/reference/1c-testing-guide.md`.
