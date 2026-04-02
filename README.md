# 1C Help — MCP в Docker

[![Test](https://github.com/mussolene/1c_hbk_helper/actions/workflows/test.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/test.yml)
[![Lint](https://github.com/mussolene/1c_hbk_helper/actions/workflows/lint.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/lint.yml)
[![Lint Commits](https://github.com/mussolene/1c_hbk_helper/actions/workflows/commitlint.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/commitlint.yml)
[![Coverage](https://codecov.io/gh/mussolene/1c_hbk_helper/graph/badge.svg)](https://codecov.io/gh/mussolene/1c_hbk_helper)
[![Release](https://github.com/mussolene/1c_hbk_helper/actions/workflows/release.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/releases)


Справка 1С: распаковка .hbk (7z), конвертация в Markdown, индексация в Qdrant, MCP-сервер для поиска и чтения справки.

Контрибьюторам: см. [CONTRIBUTING.md](CONTRIBUTING.md) (формат коммитов — Conventional Commits).

Лицензия проекта: MIT, см. [LICENSE](LICENSE). Используемые библиотеки и лицензии: см. [NOTICE](NOTICE).

**Источники форматов и логики:** разбор бинарного контейнера .hbk и оглавления (PackBlock) — по [alkoleft/hbk-viewer](https://github.com/alkoleft/hbk-viewer) (MIT). Спецификация форматов справки — [docs/help_formats.md](docs/help_formats.md).

Стандарты разработки 1С (load-standards): по умолчанию загружаются совместно [1C-Company/v8-code-style](https://github.com/1C-Company/v8-code-style) и [zeegin/v8std](https://github.com/zeegin/v8std) ([v8std.ru](https://v8std.ru)).

## Безопасность

- **MCP по HTTP** не имеет встроенной аутентификации. Предназначен **только** для доверенной среды (localhost, VPN, внутренняя сеть). При экспозиции в интернет — обязателен обратный прокси с аутентификацией.
- Не выставляйте порт 8050 (MCP) в интернет без обратного прокси с аутентификацией (nginx + Basic Auth, API key и т.п.).
- Секреты и пароли задавайте только через переменные окружения, не храните в коде или в репозитории.
- CLI (аргументы `--sources-file`, пути к каталогам) предназначен для доверенного запуска; не передавайте недоверенный ввод в аргументы.

### Конфиденциальность и NDA

- **Embedding API:** текст справки и поисковые запросы отправляются на внешний сервис. При NDA или конфиденциальных данных используйте on-prem или локальный сервис (EMBEDDING_API_URL на внутренний хост).
- **Memory и сниппеты:** хранятся на диске и в Qdrant; настройте пути в защищённое место при работе с конфиденциальным кодом (SNIPPETS_DIR, MEMORY_BASE_PATH, data/qdrant, data/config, data/standards).

## Требования

- Python 3.11+ (локально); Docker-образ — python:3.14-slim
- Docker и docker compose (для контейнерного запуска)
- 7z (p7zip-full) — для распаковки .hbk внутри контейнера

## Установка (локально)

```bash
pip install -e .
# С поддержкой MCP (Python 3.11+):
pip install -e ".[mcp]"
# Локальные эмбеддинги (EMBEDDING_BACKEND=local): добавьте extra [embed]
pip install -e ".[mcp,embed]"
# Для тестов и линтера:
pip install -e ".[dev]"
```

Без `[embed]` при `local` будет использоваться плейсхолдер (как при `none`). При `openai_api` или `none` extra `[embed]` не нужен.

## Точка входа

- **`ingest`** — загрузка и обновление индекса: поиск .hbk в каталогах (HELP_SOURCE_BASE), распаковка в **data/unpacked** (одна папка), конвертация в Markdown, индексация в Qdrant. По хэшу кэшируется. Чтобы использовать временную папку с удалением после индексации — задайте INGEST_USE_TEMP=1.
- **`reinit --force`** — полная перезагрузка: очистка коллекций и кэша, затем init (ingest + load-snippets + load-standards). Используйте для «с нуля» или после смены формата данных.

Остальные команды — вспомогательные (диагностика, один файл, только сниппеты и т.д.).

## Команды CLI

| Команда | Описание |
|--------|----------|
| **`ingest`** | Распаковать .hbk в data/unpacked (DATA_UNPACKED_DIR), построить Markdown, проиндексировать в Qdrant. Кэш по хэшу. INGEST_USE_TEMP=1 — временная папка с удалением. Опции: `--no-cache`, `--embedding-batch-size`, `--embedding-workers` |
| **`reinit [--force]`** | init (ingest + load-snippets + load-standards). С `--force` — сначала очистить коллекции и кэш, затем init. |
| **`init`** | ingest + load-snippets + load-standards (без очистки). |
| **`dashboard`** | Дашборд: задачи, ошибки, Qdrant, версии 1С. `--once` — один кадр; иначе Live с `--interval`. |
| **`mcp [directory]`** | MCP-сервер (stdio/HTTP; нужен fastmcp). Каталог по умолчанию: HELP_PATH или `data` |
| **`unpack <archive> [--output-dir]`** | Распаковать один .hbk (для диагностики) |
| **`unpack-diag <archive> [-o dir]`** | Диагностика распаковки при ошибках |
| **`unpack-dir [source_dir] [-o output]`** | Распаковать все .hbk в каталог (без индексации) |
| **`read-hbk-container <file> [--out-dir] [--toc-json]`** | Чтение .hbk как бинарного контейнера (alkoleft/hbk-viewer): сущности, извлечение в каталог |
| **`build-docs <project_dir> [--output]`** | Сгенерировать Markdown из HTML справки |
| **`build-index <directory> [--incremental] [--no-bm25] ...`** | Построить индекс по готовому каталогу .md/.html |
| **`add-bm25 [--collection] ...`** | Добавить BM25 в существующую коллекцию без пересчёта эмбеддингов |
| **`watchdog`** | Мониторинг новых .hbk, инкрементальный ingest; pending embeddings памяти |
| **`ingest-from-unpacked <dir>`** | Индексация из уже распакованного каталога (формат version/stem, как у run_unpack_sync). Не совместимо с выводом unpack-dir (version/lang/name). |
| **`parse-fastcode`** | Парсинг fastcode.ru → JSON в SNIPPETS_DIR |
| **`parse-helpf`** | Парсинг helpf.pro (по умолчанию FAQ) → JSON в SNIPPETS_DIR |
| **`qdrant-backup [-o dir]`** | Снапшот коллекций Qdrant в каталог (по умолчанию data/backup/) |
| **`qdrant-restore [-f snapshot]`** | Восстановление из снапшота (по умолчанию последний в data/backup/) |

Переменные окружения (подробнее — см. таблицу ниже и **env.example** для полного списка и таблицы префиксов). Три ключевых пути: **HELP_SOURCE_BASE** — где искать .hbk для ingest; **HELP_PATH** — откуда MCP читает топики с диска; **DATA_DIR** — корень данных (BM25, маркеры).

| Переменная | Описание | Пример / по умолчанию |
|------------|----------|------------------------|
| `QDRANT_HOST` | Хост Qdrant | `localhost` |
| `QDRANT_PORT` | Порт Qdrant | `6333` |
| `QDRANT_COLLECTION` | Имя коллекции в Qdrant | `onec_help` |
| `QDRANT_STORAGE_PATH` | Путь к каталогу хранилища Qdrant (для dashboard: вывод размера БД на диске) | — |
| `DATA_DIR` | Корень данных проекта (BM25 vocab, маркеры ingest). От него по умолчанию DATA_UNPACKED_DIR, INGEST_CACHE_FILE. | `data` |
| `HELP_PATH` | Базовый каталог справки для MCP (get_1c_help_topic с диска). В Docker: `/data`; локально: `data` или аргумент `mcp`. | Docker: `/data`; локально: `data` |
| `HELP_SOURCE_BASE` | Корень каталогов с версиями 1С для ingest (подпапки = версии, внутри — .hbk) | — |
| `HELP_SOURCE_DIRS` | Список путей через запятую (альтернатива HELP_SOURCE_BASE) | — |
| `HELP_LANGUAGES` | Языки справки (ingest) | `ru` |
| `DATA_UNPACKED_DIR` | Каталог распакованной справки (по умолчанию ingest пишет сюда) | `data/unpacked` |
| `INGEST_USE_TEMP` | `1` — временная папка с удалением после индексации (старый режим) | 0 |
| `INGEST_TEMP_DIR` | Временный каталог при INGEST_USE_TEMP=1 | — |
| `INGEST_CACHE_FILE` | Путь к файлу, чья родительская папка — каталог маркеров (load_*.running, status). Данные кэша — в Redis. В Docker — `/app/var/ingest_cache/ingest_cache.db` | `data/ingest_cache/ingest_cache.db` |
| `INGEST_SKIP_CACHE` | `1`/`true` — полная переиндексация без кэша (или `ingest --no-cache`) | — |
| `HBK_LABELS` | Человекочитаемые метки: `1cv8:Справка 1С,shcntx:Синтаксис` | — |
| `INGEST_FAILED_LOG` | Файл для списка неудачных .hbk | — |
| `MCP_TRANSPORT` | Транспорт MCP: `stdio`, `http` или `streamable-http` (для Docker/Cursor рекомендуется streamable-http) | `streamable-http` |
| `MCP_HOST` | Хост для MCP HTTP. **CLI** (`python -m onec_help mcp`): по умолчанию `127.0.0.1`. **Прямой запуск MCP-сервера** (Docker, `python -m onec_help.interfaces.mcp_server`): по умолчанию `0.0.0.0` (доступ из сети). Задайте в .env при необходимости. | CLI: `127.0.0.1`; сервер: `0.0.0.0` |
| `MCP_PORT` | Порт для MCP HTTP | `8050` |
| `MCP_PATH` | URL-путь эндпоинта MCP | `/mcp` |
| `MCP_SNIPPET_MAX_CHARS` | Макс. символов сниппета в результатах поиска | `1200` |
| `MCP_MAX_TOPIC_CHARS` | Макс. символов топика в get_1c_code_answer/search_with_content | `4000` |
| `EMBEDDING_BACKEND` | Эмбеддинги: `openai_api` (по умолчанию, Ollama), `local` (sentence-transformers), `deterministic`, `none` | `openai_api` |
| `EMBEDDING_MODEL` | Имя модели. По умолчанию `nomic-embed-text-v2-moe` (Ollama). Для local — HuggingFace id `nomic-ai/nomic-embed-text-v2-moe` | `nomic-embed-text-v2-moe` |
| `EMBEDDING_API_URL` | URL API: по умолчанию Ollama `http://localhost:11434/v1` (локально), в контейнере — `http://host.docker.internal:11434/v1` | Ollama: 11434 |
| `EMBEDDING_API_KEY` | Ключ API (если нужен для openai_api) | — |
| `EMBEDDING_DIMENSION` | Размерность при openai_api (если не задана — определяется по первому ответу API) | — |
| `EMBEDDING_BATCH_SIZE` | Размер батча для эмбеддингов. По умолчанию 32 | `32` |
| `EMBEDDING_WORKERS` | Число параллельных запросов к внешнему API (только openai_api). По умолчанию 6 | `6` |
| `EMBEDDING_FORCE_BATCH` | Максимальная мощность: `1`/`true`/`yes` — батч 256 и 16 воркеров для любого типа embedding | — |
| `EMBEDDING_MAX_CONCURRENT` | Макс. одновременных запросов к API (при ingest с несколькими воркерами снижает перегрузку LM Studio) | — |
| `BM25_ENABLED` | BM25 sparse vectors для keyword-поиска (по умолчанию 1). 0 — отключить. При инкрементальном ingest BM25 не строится (нужен полный корпус) — после ingest выполните `make add-bm25` | `1` |
| `EMBEDDING_TIMEOUT` | Таймаут HTTP-запроса к API (секунды). При ошибке — retry с backoff, затем плейсхолдер | `90` |
| `EMBEDDING_BATCH_TIMEOUT` | Таймаут для batch-запроса (секунды). По умолчанию — формула от размера батча | — |
| `MCP_MODE` | `api` — только MCP (split, по умолчанию); `full` — всё в mcp (один контейнер) | `api` |
| `WATCHDOG_ENABLED` | По умолчанию `1` — watchdog включён (split: ingest-worker; full: в фоне). `0` — отключить | `1` |
| `WATCHDOG_POLL_INTERVAL` | Интервал проверки новых .hbk (секунды) | `600` |
| `WATCHDOG_PENDING_INTERVAL` | Интервал обработки pending embeddings (секунды) | `600` |
| `WATCHDOG_INGEST_TIMEOUT` | Таймаут одного запуска ingest при работе watchdog (сек). 0 = без таймаута. | 10800 |

Полный список переменных с комментариями и таблицей префиксов (SNIPPETS_DIR, MEMORY_*, STANDARDS_REPOS, ITS_*, PRODUCTION, INDEX_STATUS_* — статус индексации, HELP_FILE_ENCODING и др.) — см. **env.example**.

## Запуск

Три варианта: **локально (pip)**, **Docker Compose**, **Make** (обёртки над compose). Все используют один CLI: `python -m onec_help <команда>`.

| Инструмент | Когда использовать |
|------------|--------------------|
| **pip + python** | Локальная разработка, отладка, без Docker |
| **docker compose** | Запуск в контейнерах (рекомендуется) |
| **make** | Обёртки над compose; `make help` — полный список |

**Быстрый старт (Docker):** `make up` (qdrant + mcp) → при необходимости индексации: `make ingest-up` → MCP: http://localhost:8050/mcp. Данные в `./data/`. Если пропала база (data/qdrant): `make ensure-data && make up`; для индекса: `make ingest-up`. Локально: `python -m onec_help mcp` без аргументов использует каталог `data/` по умолчанию.

---

### 1. Локально (pip)

```bash
pip install -e ".[mcp]"
# Qdrant (Docker): docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0

HELP_SOURCE_BASE=/opt/1cv8 python -m onec_help ingest
python -m onec_help mcp . --transport streamable-http --host 0.0.0.0 --port 8050
```

Подробнее: [docs/run.md](docs/run.md).

---

### 2. Docker Compose

Данные в `./data/`. MCP: http://localhost:8050/mcp.

**Важно:** проект использует два файла: `docker-compose.base.yml` (образы, сервисы) и `docker-compose.yml` (переменные). Команда **`docker compose up -d` без `-f` выдаст ошибку** «service "mcp" has neither an image nor a build context». Используйте **`make up`** или явно: **`docker compose -f docker-compose.base.yml -f docker-compose.yml up -d`**.

**macOS:** Docker Desktop → Settings → Resources → File sharing — добавьте `/opt` (или `/opt/1cv8`).

| Действие | Команда |
|----------|---------|
| Запуск (qdrant + mcp) | `make up` или `docker compose -f docker-compose.base.yml -f docker-compose.yml up -d` |
| Запуск ingest-worker | `make ingest-up` (профиль ingest) |
| Запуск full (один контейнер) | `docker compose -f docker-compose.base.yml -f docker-compose.full.yml up -d` |
| Индексация | `make ingest` (нужен запущенный ingest-worker: `make ingest-up`) |
| Индексация (full) | `docker compose -f docker-compose.base.yml -f docker-compose.full.yml exec mcp python -m onec_help ingest` |
| Полная перезагрузка | `docker compose -f docker-compose.base.yml -f docker-compose.yml exec ingest-worker python -m onec_help reinit --force` (или для full: `exec mcp ...`) |
| Статус индекса | `docker compose -f docker-compose.base.yml -f docker-compose.yml exec mcp python -m onec_help dashboard --once` |

---

### 3. Make (обёртки над Docker Compose)

`make help` — полный список. Частые команды:

| Команда | Описание |
|---------|----------|
| `make up` | Запуск qdrant + mcp (по умолчанию только эти два сервиса) |
| `make ingest-up` | Запуск ingest-worker (watchdog, индексация) |
| `make ingest-down` | Остановка ingest-worker |
| `make up-full` | Запуск full (один контейнер mcp) |
| `make ingest` | Индексация справки (единая точка входа) |
| `make ingest-full` | Индексация в режиме full |
| `make reinit ARGS='--force'` | Полная перезагрузка: очистка + ingest + snippets + standards |
| `make init` | ingest + load-snippets + load-standards (без очистки) |
| `make dashboard` | Дашборд (статус индекса, задачи, ошибки). ARGS='--once' — один кадр |
| `make ensure-data` | Создать data/qdrant и др. (после потери базы) |
| `make load-snippets` | Загрузить сниппеты из SNIPPETS_DIR |
| `make load-standards` | Загрузить стандарты (v8-code-style, v8std) |
| `make snippets` | parse-fastcode + parse-helpf + load-snippets |

Аргументы CLI: `make ingest ARGS="--no-cache --workers 4"`.

---

### Режимы развёртывания

- **По умолчанию (`make up`):** только qdrant + mcp. Для индексации и watchdog: **`make ingest-up`** (поднимает ingest-worker).
- **Full:** один контейнер mcp; cron раз в сутки. `make up-full`, `make ingest-full`.

Просмотр справки в браузере может быть реализован в будущем отдельным контейнером (по аналогии с BSL LS).

---

### BSL LS (диагностика и рефакторинг 1С)

Для статического анализа и навигации по коду 1С используется **BSL Language Server** через отдельный внешний MCP — **lsp-bsl-bridge**. Этот репозиторий **не разрабатывает** lsp-bsl-bridge и не меняет его API или поведение: здесь поддерживается только интеграционный контракт и guidance по совместному использованию с `1c-help`. Запуск: `make bsl-start` (или `docker compose -f docker-compose.bsl.yml up -d`). Требуется клон репозитория mcp-bsl-lsp-bridge в `deps/` (`make fetch-bsl-bridge`). В Cursor в `.cursor/mcp.json` добавляют оба сервера: 1c-help (справка, память, метаданные) и внешний lsp-bsl-bridge (document_diagnostics, project_analysis, symbol_explore и др.). Подробнее: [docs/bsl-ls-mcp-setup.md](docs/bsl-ls-mcp-setup.md), [docs/cursor-examples/](docs/cursor-examples/README.md).

---

### Ingest: мультикаталоги и расписание

Ingest берёт .hbk из `HELP_SOURCE_BASE` (подпапки = версии 1С). Путь к .hbk: `/opt/1cv8/8.3.27.../1cv8_ru.hbk` или `.../bin/1cv8_ru.hbk` (поиск рекурсивный).

- **Вручную:** сначала `make ingest-up`, затем `make ingest` (или `docker compose exec ingest-worker python -m onec_help ingest`)
- **Cron:** full — 3:00; при `make ingest-up` в ingest-worker работает watchdog
- **Watchdog** (по умолчанию включён): мониторинг .hbk, STANDARDS_DIR и SNIPPETS_DIR; при изменениях — ingest / load-standards / load-snippets; периодически — pending memory. Отключить: `WATCHDOG_ENABLED=0`.

Кэш: в Docker путь к файлу кэша — `/app/var/ingest_cache/ingest_cache.db` (volume `ingest_cache` → обычно `./data/ingest_cache` на хосте). Переменная `INGEST_CACHE_FILE` задаёт путь внутри контейнера. При `[ingest] WARN: ingest cache read failed` — проверьте права, существование каталога и место на диске. `reinit --force` стирает кэш.

---

### Эмбеддинги: как пользоваться

По умолчанию используется **Ollama** — переменные задавать не нужно.

1. **Установить и запустить Ollama**, один раз выполнить:
   ```bash
   ollama pull nomic-embed-text-v2-moe
   ```
2. **Запускать проект как обычно** (`make up`, `make ingest-up` и т.д.) — переменные для эмбеддингов можно не задавать.
3. **Локально (без Docker):** достаточно запущенного Ollama с этой моделью на `localhost:11434`.
4. **В Docker** контейнеры по умолчанию обращаются к Ollama на хосте по `host.docker.internal:11434` — Ollama должен быть запущен на машине с Docker.

**Другие бэкенды:** если нужен LM Studio или local (sentence-transformers), задайте в `.env` бэкенд, URL и модель (примеры в **env.example**). Подробнее: [docs/embedding.md](docs/embedding.md), [docs/embedding-models-analysis.md](docs/embedding-models-analysis.md).

---

### Эмбеддинги (переменные)

| Режим | Описание |
|-------|----------|
| `none` | Плейсхолдеры; только search_1c_help_keyword |
| `deterministic` | 768 dim без модели; воспроизводимый поиск |
| `openai_api` | Ollama по умолчанию (11434); LM Studio — задать `EMBEDDING_API_URL` в .env |
| `local` | sentence-transformers в контейнере; образ по умолчанию без них, с local: `docker compose build --build-arg EMBEDDING_BACKEND=local` |

Образ Docker по умолчанию собирается без sentence-transformers (только openai_api/deterministic). Для образа с local-эмбеддингами: `docker compose build --build-arg EMBEDDING_BACKEND=local`.

---

### Один контейнер без Compose

```bash
docker run --rm -d -p 8050:8050 \
  -v /opt/1cv8:/opt/1cv8:ro \
  -e QDRANT_HOST=host.docker.internal -e QDRANT_PORT=6333 \
  -e HELP_SOURCE_BASE=/opt/1cv8 \
  --name onec-help-mcp $(docker build -q .) \
  /app/entrypoint.sh python -m onec_help mcp /data --transport streamable-http --host 0.0.0.0 --port 8050
```

## MCP

| Инструмент | Назначение |
|------------|------------|
| **search_1c_help** | Семантический поиск по справке. |
| **search_1c_help_keyword** | Поиск по вхождению строки (точные термины: имена API, параметры запуска). |
| **get_1c_help_topic** | Полный текст темы по пути (с диска или из Qdrant). |
| **get_1c_function_info** | Описание функции/метода 1С по имени. |
| **list_1c_help_titles** | Список заголовков и путей; фильтр по началу пути (например `zif`). |
| **get_1c_help_index_status** | Статус индекса: число тем, версии, языки. |

**Рекомендация:** для точных имён — сначала **search_1c_help_keyword**; для общих вопросов — **search_1c_help**.

Конфиг Cursor: **`.cursor/mcp.json`** (пример — `docs/mcp.json.example`). MCP по HTTP (порт 8050). После правок конфига Cursor перезапускают.

**Если Cursor пишет «connect ECONNREFUSED 127.0.0.1:8050»:** проверьте `docker compose up -d`, `docker compose ps`, `docker compose logs mcp`.

**Если в логах MCP «fetch failed» или «read ECONNRESET»:** соединение обрывается со стороны сервера. (1) В логах контейнера ищите причину: `docker compose logs mcp --tail 100` — при падении сервера по исключению появится строка «MCP server exited» и traceback. (2) Контейнер должен слушать на `0.0.0.0:8050`, путь `/mcp` задаётся в command (в base compose явно передан `--path /mcp`). (3) URL в `.cursor/mcp.json`: `http://localhost:8050/mcp` без завершающего слэша. (4) Проверка без Cursor: после `docker compose up -d` выполнить `curl -v http://localhost:8050/mcp` — ответ не должен обрываться (ECONNRESET). Если обрывается — пересобрать образ: `docker compose build mcp && docker compose up -d mcp` и снова посмотреть логи.

**MCP контейнер долго стартует или не поднимается:** по умолчанию в base compose задано `MCP_MODE=api` — в контейнере не запускается фоновый ingest/cron/watchdog, только процесс MCP (быстрый старт). Если нужен один контейнер «всё в одном» с ingest по расписанию — задайте `MCP_MODE=full` в `.env` (тогда при старте в фоне запустится `python -m onec_help ingest`, это тяжело и может замедлить поднятие MCP).

**Сервер запущен, но Cursor не показывает tools или «No server info found»:** в base compose по умолчанию задано `MCP_TRANSPORT=sse` (лучше совместим с Cursor). Убедитесь: (1) контейнер перезапущен после смены транспорта: `docker compose -f docker-compose.base.yml up -d mcp`; (2) в Cursor URL именно `http://localhost:8050/mcp`; (3) **полностью перезапустите Cursor** (Quit и снова открыть), не только перезагрузка окна; (4) в настройках MCP дождитесь появления сервера и списка tools (иногда 5–10 с). Если по-прежнему пусто — в логах Cursor (Output → MCP) смотрите ошибки; при `ECONNRESET` проверьте, что порт 8050 не занят и файрвол не режет соединение.

**MCP подключается, но не работает или отваливается:**
1. Контейнер mcp запущен: `docker compose ps` — сервис `mcp` в состоянии Up (ingest-worker опционален: `make ingest-up`).
2. Порт 8050 слушается: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8050/` (ожидается ответ от сервера, не 000).
3. Конфиг Cursor: в `.cursor/mcp.json` для 1c-help указано `"url": "http://localhost:8050/mcp"` (без опечаток; порт совпадает с MCP_PORT).
4. После смены конфига или порта — полностью перезапустить Cursor (не только перезагрузка окна).
5. Индекс есть: вызвать инструмент `get_1c_help_index_status` — если «Index does not exist», выполнить `make ingest`.
6. Логи: `docker compose logs mcp --tail 100` — смотреть на ошибки Python/Qdrant при запросах.

## Тесты и линт

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70
ruff check src tests && ruff format --check src tests
```

Покрытие не менее 70% (исключены из расчёта: `__main__.py`, `tests/`).

### Интеграционные и нагрузочные тесты MCP

Требуют запущенные MCP и Qdrant (например `make up` или `make ingest-up`).

- **Интеграционные тесты (в т.ч. крипто-сценарии):**  
  `MCP_INTEGRATION=1 PYTHONPATH=src python -m pytest tests/test_mcp_integration.py tests/test_mcp_functional_crypto.py -v`  
  Список запросов для функциональных проверок: [tests/fixtures/mcp_crypto_queries.json](tests/fixtures/mcp_crypto_queries.json).

- **Релевантность и полнота ответов, верификация скиллов/правил:**  
  [docs/mcp-quality-test-report.md](docs/mcp-quality-test-report.md), [docs/skills-rules-verification.md](docs/skills-rules-verification.md). Для тестов с проектом из `.nosync` (библиотека криптографии) задайте при необходимости `NOSYNC_DIR` (путь к корню проекта).

## CI

- **test** — pytest, покрытие ≥70%, матрица Python 3.11–3.14; Codecov (`CODECOV_TOKEN` в secrets).
- **lint** — ruff check, ruff format.
- **commitlint** — conventional commits.
- **release** — при push тега `v*`: changelog (git-cliff), sdist, GitHub Release.

## Документация

- `make help` — все команды Makefile (unpack-help, up, ingest, up-full, ingest-full и др.)
- [docs/architecture.md](docs/architecture.md) — сервисы, режимы развёртывания (single/split), ответственность.
- [docs/embedding.md](docs/embedding.md) — embedding-пайплайн: бэкенды, batch/single, retry, 429, переменные окружения.
- [docs/run.md](docs/run.md) — запуск локально и в Docker.
- [docs/search-and-mcp.md](docs/search-and-mcp.md) — поиск и рекомендации по MCP.
- [docs/mcp-tools-reference.md](docs/mcp-tools-reference.md) — справочник MCP-инструментов 1c-help: параметры, лимиты, рекомендуемый порядок вызовов.
- [docs/help_formats.md](docs/help_formats.md) — форматы справки (.hbk, HTML, Markdown).
- [docs/mcp.json.example](docs/mcp.json.example) — пример конфига MCP для Cursor.
- [docs/bsl-ls-mcp-setup.md](docs/bsl-ls-mcp-setup.md) — подключение BSL LS как MCP (make bsl-start, URI для document_diagnostics).
- [docs/cursor-examples/](docs/cursor-examples/README.md) — Skill и Rules для Cursor (1c-help + BSL LS); эталон для индексации; при доработке MCP обновлять как зависимость.
- [docs/mcp-quality-test-report.md](docs/mcp-quality-test-report.md) — шаблон отчёта по релевантности и полноте ответов MCP.
- [docs/skills-rules-verification.md](docs/skills-rules-verification.md) — верификация скиллов и правил (workflow агента).

## Дальнейшие этапы

Планируются MCP по кодовой базе и метаданным 1С (индексированный поиск по коду, подсказки по разработке). Структура репозитория допускает добавление сервисов `mcp-codebase` и `mcp-metadata` в compose.
