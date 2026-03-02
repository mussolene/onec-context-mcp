# 1C Help — MCP в Docker

[![Test](https://github.com/mussolene/1c_hbk_helper/actions/workflows/test.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/test.yml)
[![Lint](https://github.com/mussolene/1c_hbk_helper/actions/workflows/lint.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/lint.yml)
[![Lint Commits](https://github.com/mussolene/1c_hbk_helper/actions/workflows/commitlint.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/actions/workflows/commitlint.yml)
[![Coverage](https://codecov.io/gh/mussolene/1c_hbk_helper/graph/badge.svg)](https://codecov.io/gh/mussolene/1c_hbk_helper)
[![Release](https://github.com/mussolene/1c_hbk_helper/actions/workflows/release.yml/badge.svg)](https://github.com/mussolene/1c_hbk_helper/releases)


Справка 1С: распаковка .hbk (7z), конвертация в Markdown, индексация в Qdrant, MCP-сервер для поиска и чтения справки.

Контрибьюторам: см. [CONTRIBUTING.md](CONTRIBUTING.md) (формат коммитов — Conventional Commits).

Лицензия проекта: MIT, см. [LICENSE](LICENSE). Используемые библиотеки и лицензии: см. [NOTICE](NOTICE).

Стандарты разработки 1С (load-standards): по умолчанию загружаются совместно [1C-Company/v8-code-style](https://github.com/1C-Company/v8-code-style) и [zeegin/v8std](https://github.com/zeegin/v8std) ([v8std.ru](https://v8std.ru)).

## Безопасность

- **Веб (serve)** и **MCP по HTTP** не имеют встроенной аутентификации. Предназначены **только** для доверенной среды (localhost, VPN, внутренняя сеть). При экспозиции в интернет — обязателен обратный прокси с аутентификацией.
- Не выставляйте порты 5000 (Flask) и 8050 (MCP) в интернет без обратного прокси с аутентификацией (nginx + Basic Auth, API key и т.п.).
- **HELP_SERVE_ALLOWED_DIRS** — обязательна для serve: без неё форма просмотра справки не принимает пути (защита от чтения произвольных каталогов). Задайте список разрешённых базовых каталогов через запятую.
- Секреты и пароли задавайте только через переменные окружения, не храните в коде или в репозитории.
- CLI (аргументы `--sources-file`, пути к каталогам) предназначен для доверенного запуска; не передавайте недоверенный ввод в аргументы.

### Конфиденциальность и NDA

- **Embedding API:** текст справки и поисковые запросы отправляются на внешний сервис. При NDA или конфиденциальных данных используйте on-prem сервис (EMBEDDING_API_URL на внутренний хост).
- **Memory и сниппеты:** хранятся на диске и в Qdrant; настройте пути в защищённое место при работе с конфиденциальным кодом.

## Требования

- Python 3.10+ (локально); Docker-образ — python:3.14-slim
- Docker и docker compose (для контейнерного запуска)
- 7z (p7zip-full) — для распаковки .hbk внутри контейнера

## Установка (локально)

```bash
pip install -e .
# С поддержкой MCP (Python 3.10+):
pip install -e ".[mcp]"
# Локальные эмбеддинги (EMBEDDING_BACKEND=local): добавьте extra [embed]
pip install -e ".[mcp,embed]"
# Для тестов и линтера:
pip install -e ".[dev]"
```

Без `[embed]` при `local` будет использоваться плейсхолдер (как при `none`). При `openai_api` или `none` extra `[embed]` не нужен.

## Команды CLI

| Команда | Описание |
|--------|----------|
| **`unpack <archive> [--output-dir]`** | Распаковать один .hbk (7z → zipfile → offset → unzip → scan local headers) |
| **`unpack-diag <archive> [-o dir]`** | Диагностика распаковки: пробует каждый метод, печатает результат (при «All unpack methods failed») |
| **`unpack-dir [source_dir] [-o output]`** | Распаковать все .hbk из дерева каталогов в указанную директорию (без индексации). Источники: `source_dir`, `HELP_SOURCE_BASE` или `--sources` |
| **`build-docs <project_dir> [--output]`** | Сгенерировать Markdown из HTML справки |
| **`build-index <directory> [--incremental] [--no-bm25] [--embedding-batch-size N] [--embedding-workers N]`** | Построить векторный индекс в Qdrant по .md/.html. По умолчанию BM25 sparse vectors включены (BM25_ENABLED=1). `--no-bm25` — отключить. |
| **`add-bm25 [--collection] [--batch-size N]`** | Добавить BM25 sparse vectors в существующую коллекцию **без re-ingest** и без пересчёта эмбеддингов. Используйте для миграции старых индексов. |
| **`ingest`** | Распаковать .hbk из мультикаталогов во временную папку, построить Markdown, проиндексировать в Qdrant, удалить временные данные. По хэшу .hbk кэшируется факт индексации — при перезапуске неизменённые файлы пропускаются (не парсятся, не пересчитываются эмбеддинги). Опции `--no-cache` для полной переиндексации; `--embedding-batch-size`, `--embedding-workers` — для ускорения эмбеддингов |
| **`index-status`** | Статус индекса: число тем, число эмбеддингов, размер БД на диске (если задан `QDRANT_STORAGE_PATH`), версии и языки; при запущенном ingest — скорость эмбеддингов, прогресс по папкам, ETA |
| **`watchdog`** | Мониторинг новых .hbk в HELP_SOURCE_BASE, инкрементальный ingest при появлении; обработка pending embeddings памяти каждые N минут |
| **`serve <directory>`** | Веб-просмотр справки (Flask) |
| **`mcp <directory>`** | MCP-сервер (stdio/HTTP; нужен fastmcp) |

Переменные окружения (подробнее — см. таблицу ниже): `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`, `HELP_PATH`, `HELP_SOURCE_BASE`, `HELP_SOURCES_DIR`, `HELP_SOURCE_DIRS`, `HELP_LANGUAGES`, `HELP_INGEST_TEMP`, `INGEST_FAILED_LOG`, `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_PATH`, `PORT`.

| Переменная | Описание | Пример / по умолчанию |
|------------|----------|------------------------|
| `QDRANT_HOST` | Хост Qdrant | `localhost` |
| `QDRANT_PORT` | Порт Qdrant | `6333` |
| `QDRANT_COLLECTION` | Имя коллекции в Qdrant | `onec_help` |
| `QDRANT_STORAGE_PATH` | Путь к каталогу хранилища Qdrant (для `index-status`: вывод размера БД на диске) | — |
| `HELP_PATH` | Базовый каталог справки (для MCP/serve) | `/data` |
| `HELP_SOURCE_BASE` | Корень каталогов с версиями 1С (ingest) | — |
| `HELP_SOURCES_DIR` | То же, альтернативное имя | — |
| `HELP_SOURCE_DIRS` | Список путей через запятую (ingest) | — |
| `HELP_LANGUAGES` | Языки справки (ingest) | `ru` |
| `HELP_INGEST_TEMP` | Временный каталог для ingest (если не задан — `$TMPDIR/help_ingest` или `tempfile.gettempdir()`) | — |
| `HELP_SERVE_HOST` | Хост для serve (127.0.0.1 — только localhost; 0.0.0.0 — для Docker) | `127.0.0.1` |
| `INGEST_CACHE_FILE` | Путь к SQLite-кэшу: хэш .hbk, статус ingest. Ingest и index-status читают/пишут в одну БД. В Docker — `/app/var/ingest_cache/ingest_cache.db` (volume `ingest_cache`) | `data/ingest_cache/ingest_cache.db` |
| `INGEST_SKIP_CACHE` | `1`/`true` — полная переиндексация без кэша (или `ingest --no-cache`) | — |
| `INGEST_FAILED_LOG` | Файл для списка неудачных .hbk | — |
| `MCP_TRANSPORT` | Транспорт MCP: `stdio`, `http` или `streamable-http` (для Docker/Cursor рекомендуется streamable-http) | `streamable-http` |
| `MCP_HOST` | Хост для MCP HTTP | `127.0.0.1` |
| `MCP_PORT` | Порт для MCP HTTP | `8050` |
| `MCP_PATH` | URL-путь эндпоинта MCP | `/mcp` |
| `MCP_SNIPPET_MAX_CHARS` | Макс. символов сниппета в результатах поиска | `1200` |
| `MCP_MAX_TOPIC_CHARS` | Макс. символов топика в get_1c_code_answer/search_with_content | `4000` |
| `PORT` | Порт веб-сервера (serve) | `5000` |
| `SERVE_PORT` | Порт serve в Docker (split, профиль serve) | `5000` |
| `HELP_SERVE_ALLOWED_DIRS` | Список путей через запятую (serve): разрешённые базовые каталоги для формы; если задан, ввод вне списка отклоняется | — |
| `EMBEDDING_BACKEND` | Эмбеддинги: `local` (sentence-transformers), `openai_api` (внешний API), `deterministic` (детерминированные векторы 384 dim без модели — только БД) или `none` (плейсхолдер, только поиск по ключевым словам) | `openai_api` |
| `EMBEDDING_MODEL` | Имя модели. Для openai_api (LM Studio): если такой модели нет на сервере, берётся первая из списка или популярная (text-text-embedding-mxbai-embed-large-v1, nomic-embed-text, all-MiniLM-L6-v2); для local — all-MiniLM-L6-v2 | `text-text-embedding-mxbai-embed-large-v1` (openai_api) |
| `EMBEDDING_API_URL` | Для openai_api: базовый URL (по умолчанию LM Studio: `http://localhost:1234/v1` локально, в контейнере — `http://host.docker.internal:1234/v1`). При недоступности/ошибках используются плейсхолдер-векторы и семантический поиск ограничен | LM Studio: 1234 |
| `EMBEDDING_API_KEY` | Ключ API (если нужен для openai_api) | — |
| `EMBEDDING_DIMENSION` | Размерность при openai_api (если не задана — определяется по первому ответу API) | — |
| `EMBEDDING_BATCH_SIZE` | Размер батча для эмбеддингов (текстов за один вызов encode/API). По умолчанию 64 | `64` |
| `EMBEDDING_WORKERS` | Число параллельных запросов к внешнему API (только openai_api). По умолчанию 4 | `4` |
| `EMBEDDING_FORCE_BATCH` | Максимальная мощность: `1`/`true`/`yes` — батч 256 и 16 воркеров для любого типа embedding | — |
| `EMBEDDING_MAX_CONCURRENT` | Макс. одновременных запросов к API (при ingest с несколькими воркерами снижает перегрузку LM Studio) | — |
| `BM25_ENABLED` | BM25 sparse vectors для keyword-поиска (по умолчанию 1). 0 — отключить. `add-bm25` — миграция без re-ingest | `1` |
| `EMBEDDING_TIMEOUT` | Таймаут HTTP-запроса к API (секунды). При ошибке — retry с backoff, затем плейсхолдер | `60` |
| `EMBEDDING_BATCH_TIMEOUT` | Таймаут для batch-запроса (секунды). По умолчанию — формула от размера батча | — |
| `MCP_MODE` | `api` — только MCP (split, по умолчанию); `full` — всё в mcp (один контейнер) | `api` |
| `WATCHDOG_ENABLED` | `1` — запустить watchdog в фоне: мониторинг .hbk и обработка pending memory | `0` |
| `WATCHDOG_POLL_INTERVAL` | Интервал проверки новых .hbk (секунды) | `600` |
| `WATCHDOG_PENDING_INTERVAL` | Интервал обработки pending embeddings (секунды) | `600` |

## Запуск

Три варианта: **локально (pip)**, **Docker Compose**, **Make** (обёртки над compose). Все используют один CLI: `python -m onec_help <команда>`.

| Инструмент | Когда использовать |
|------------|--------------------|
| **pip + python** | Локальная разработка, отладка, без Docker |
| **docker compose** | Запуск в контейнерах (рекомендуется) |
| **make** | Обёртки над compose; `make help` — полный список |

**Быстрый старт (Docker):** `make up` → `make ingest` → MCP: http://localhost:8050/mcp. Данные в `./data/`.

---

### 1. Локально (pip)

```bash
pip install -e ".[mcp]"
# Qdrant (Docker): docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant:v1.12.0

HELP_SOURCE_BASE=/opt/1cv8 python -m onec_help ingest
python -m onec_help mcp . --transport streamable-http --host 0.0.0.0 --port 8050
python -m onec_help serve ./unpacked   # HELP_SERVE_ALLOWED_DIRS обязательна
```

Подробнее: [docs/run.md](docs/run.md).

---

### 2. Docker Compose

Данные в `./data/`. MCP: http://localhost:8050/mcp.

**macOS:** Docker Desktop → Settings → Resources → File sharing — добавьте `/opt` (или `/opt/1cv8`).

| Действие | Команда |
|----------|---------|
| Запуск (split) | `docker compose up -d` |
| Запуск + веб (serve) | `docker compose --profile serve up -d` |
| Запуск full (один контейнер) | `docker compose -f docker-compose.full.yml up -d` |
| Индексация (split) | `docker compose exec ingest-worker python -m onec_help ingest` |
| Индексация (full) | `docker compose -f docker-compose.full.yml exec mcp python -m onec_help ingest` |
| Статус индекса | `docker compose exec mcp python -m onec_help index-status` |
| Распаковка без индекса | `docker compose run --rm -v /opt/1cv8:/input:ro -v $(pwd)/data/unpacked:/output mcp python -m onec_help unpack-dir /input -o /output -l ru` |

---

### 3. Make (обёртки над Docker Compose)

`make help` — полный список. Частые команды:

| Команда | Описание |
|---------|----------|
| `make up` | Запуск split (qdrant + mcp + ingest-worker) |
| `make up-full` | Запуск full (один контейнер mcp) |
| `make up-serve` | Split + веб-просмотр (порт 5000) |
| `make ingest` | Индексация .hbk (split) |
| `make ingest-full` | Индексация (full) |
| `make index-status` | Статус индекса |
| `make unpack-help` | Распаковка .hbk в data/unpacked (без индекса) |
| `make init` | ingest + load-snippets + load-standards |
| `make reinit ARGS='--force'` | Стереть коллекции и кэш, затем init |
| `make load-snippets` | Загрузить сниппеты из SNIPPETS_DIR |
| `make load-standards` | Загрузить стандарты (v8-code-style, v8std) |
| `make snippets` | parse-fastcode + parse-helpf + load-snippets |

Аргументы CLI: `make ingest ARGS="--no-cache --workers 4"`.

---

### Режимы развёртывания

- **Split (по умолчанию):** mcp (API) + ingest-worker (batch). Cron в ingest-worker.
- **Full:** один контейнер mcp; cron раз в сутки. `make up-full`, `make ingest-full`.
- **Serve:** split + веб (Flask:5000). Требуется `./data/unpacked`.

---

### Ingest: мультикаталоги и расписание

Ingest берёт .hbk из `HELP_SOURCE_BASE` (подпапки = версии 1С). Путь к .hbk: `/opt/1cv8/8.3.27.../1cv8_ru.hbk` или `.../bin/1cv8_ru.hbk` (поиск рекурсивный).

- **Вручную:** `make ingest` или `docker compose exec ingest-worker python -m onec_help ingest`
- **Cron:** full — 3:00; split — настраивается в ingest-worker
- **Watchdog** (`WATCHDOG_ENABLED=1`): мониторинг новых .hbk + pending memory

Кэш: volume `ingest_cache`. При `[ingest] WARN: ingest cache read failed` — права, диск. `reinit --force` стирает кэш.

---

### Эмбеддинги

| Режим | Описание |
|-------|----------|
| `none` | Плейсхолдеры; только search_1c_help_keyword |
| `deterministic` | 384 dim без модели; воспроизводимый поиск |
| `openai_api` | LM Studio, Ollama; `EMBEDDING_API_URL` в .env |
| `local` | sentence-transformers в контейнере; build-arg при сборке |

При `openai_api`/`none`/`deterministic` sentence-transformers не ставится. Сборка без них: `EMBEDDING_BACKEND=none docker compose build`.

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

## Тесты и линт

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest tests -v --cov=src/onec_help --cov-report=term-missing --cov-fail-under=70
ruff check src tests && ruff format --check src tests
```

Покрытие не менее 70% (исключены из расчёта: `__main__.py`, `tests/`).

## CI

- **test** — pytest, покрытие ≥70%, матрица Python 3.10–3.14; Codecov (`CODECOV_TOKEN` в secrets).
- **lint** — ruff check, ruff format.
- **commitlint** — conventional commits.
- **release** — при push тега `v*`: changelog (git-cliff), sdist, GitHub Release.

## Документация

- `make help` — все команды Makefile (unpack-help, up, ingest, up-full, ingest-full и др.)
- [docs/architecture.md](docs/architecture.md) — сервисы, режимы развёртывания (single/split), ответственность.
- [docs/embedding.md](docs/embedding.md) — embedding-пайплайн: бэкенды, batch/single, retry, 429, переменные окружения.
- [docs/run.md](docs/run.md) — запуск локально и в Docker.
- [docs/search-and-mcp.md](docs/search-and-mcp.md) — поиск и рекомендации по MCP.
- [docs/help_formats.md](docs/help_formats.md) — форматы справки (.hbk, HTML, Markdown).
- [docs/mcp.json.example](docs/mcp.json.example) — пример конфига MCP для Cursor.
- [docs/cursor-examples/](docs/cursor-examples/README.md) — Skill и Rules для Cursor (1c-help + BSL LS); эталон для индексации; при доработке MCP обновлять как зависимость.

## Дальнейшие этапы

Планируются MCP по кодовой базе и метаданным 1С (индексированный поиск по коду, подсказки по разработке). Структура репозитория допускает добавление сервисов `mcp-codebase` и `mcp-metadata` в compose.
